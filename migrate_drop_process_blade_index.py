"""迁移脚本：移除 iot_process_log 上已不再使用的复合索引 ix_iot_process_log_device_blade_time。

背景：
  早期在「窗口函数去重」优化中，我们为 iot_process_log 加了 (device_id, blade_id, event_time)
  复合索引，意图覆盖「每 blade_id 取 event_time 最新一条」的窗口函数去重。

  经核查，写入侧对 (device_id, blade_id) 已做 upsert（ON DUPLICATE KEY UPDATE，最新一条覆盖），
  存储层每个 (device, blade) 恒为 1 行，读取时不再需要按 blade_id 去重。相关去重查询
  （webhook_service 的 query_flatness_statistics / query_device_process_statistics、report_service
  的 _fetch_process_logs）已全部回退为普通带时间排序的查询，该窗口函数去重逻辑已移除。

  因此 iot_process_log 上的这份复合索引属于「死索引」：每次推送写入都要额外维护它，却零读取收益。

  模型定义（app/models/iot_event.py）已移除该 Index()，新环境 create_all 不会建它。
  但已执行过 migrate_add_time_index.py --apply 的存量环境里索引已存在，不会自动消失，
  需用本脚本显式 DROP。

  本脚本幂等：先查 information_schema 判断索引是否存在，存在才 DROP，可重复执行。
  删除二级索引是 Online DDL（MySQL 8 / InnoDB 默认 INPLACE），一般不阻塞读写。

用法：
  python migrate_drop_process_blade_index.py            # 预检：打印索引是否存在（不改动数据库）
  python migrate_drop_process_blade_index.py --apply    # 执行：仅存在的索引会被删除
"""
import asyncio
import sys

from sqlalchemy import text

from app.database import async_session


INDEX = ("iot_process_log", "ix_iot_process_log_device_blade_time")


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
    print(f"移除 iot_process_log 死索引 {index}")
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
        print("以上为预检结果。确认无误后运行：python migrate_drop_process_blade_index.py --apply")


if __name__ == "__main__":
    asyncio.run(main())
