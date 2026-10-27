"""迁移脚本：移除 iot_flatness_data 上未被查询使用的复合索引 ix_iot_flatness_device_blade_time。

背景：
  在「窗口函数去重」优化中，我们为 iot_process_log 与 iot_flatness_data 各加了一份
  (device_id, blade_id, event_time) 复合索引，意图覆盖「每 blade_id 取 event_time 最新一条」的
  窗口函数去重。

  经核查，所有窗口函数去重查询（webhook_service / report_service 中的
  _build_latest_per_blade_subq）只作用在 IotProcessLog 上；IotFlatnessData 没有任何去重查询，
  其实用查询（列表 / 精确查询 / 下载）由 (device_id, event_time) 与单列 blade_id 索引覆盖。
  因此 iot_flatness_data 上的这份复合索引属于「死索引」：每次推送写入都要额外维护它，却零读取收益。

  模型定义（app/models/iot_event.py）已移除该 Index()，新环境 create_all 不会建它。
  但已执行过 migrate_add_time_index.py --apply 的存量环境里索引已存在，不会自动消失，
  需用本脚本显式 DROP。

  本脚本幂等：先查 information_schema 判断索引是否存在，存在才 DROP，可重复执行。
  删除二级索引是 Online DDL（MySQL 8 / InnoDB 默认 INPLACE），一般不阻塞读写。

用法：
  python migrate_drop_flatness_blade_index.py            # 预检：打印索引是否存在（不改动数据库）
  python migrate_drop_flatness_blade_index.py --apply    # 执行：仅存在的索引会被删除
"""
import asyncio
import sys

from sqlalchemy import text

from app.database import async_session


INDEX = ("iot_flatness_data", "ix_iot_flatness_device_blade_time")


async def index_exists(db, table: str, index: str) -> bool:
    row = await db.execute(
        text(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :tbl AND index_name = :idx LIMIT 1"
        ),
        {"tbl": table, "idx": index},
    )
    return row.first() is not None


async def drop_index(db, table: str, index: str):
    await db.execute(text(f"ALTER TABLE `{table}` DROP INDEX `{index}`"))
    await db.commit()


async def main():
    apply = "--apply" in sys.argv
    table, index = INDEX
    print("=" * 60)
    print(f"移除 iot_flatness_data 死索引 {index}")
    print("=" * 60)
    print(f"模式: {'执行 (--apply)' if apply else '预检（仅检查，不改数据库）'}")
    print("-" * 60)

    async with async_session() as db:
        exists = await index_exists(db, table, index)
        if not exists:
            print(f"  [不存在] {table}.{index} —— 无需处理")
        elif apply:
            try:
                await drop_index(db, table, index)
                print(f"  [已删除] {table}.{index}")
            except Exception as e:  # noqa: BLE001
                await db.rollback()
                print(f"  [失败]   {table}.{index}: {e}")
        else:
            print(f"  [存在]   {table}.{index}  → 需执行 --apply 删除")

    print("-" * 60)
    if not apply:
        print("以上为预检结果。确认无误后运行：python migrate_drop_flatness_blade_index.py --apply")


if __name__ == "__main__":
    asyncio.run(main())
