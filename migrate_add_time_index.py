"""迁移脚本：为 iot_process_log / iot_flatness_data 的 event_time 补充时间索引。

背景：
  两表是平台的"大表"，几乎所有统计 / 列表 / 报表查询都按 event_time 倒序或按时间范围过滤，
  但 event_time 此前没有任何索引。数据累积到几十万 / 百万行后，排序与时间区间过滤会退化成
  全表扫描 + filesort，接口明显变慢。

  同时为"按设备维度的时间查询"补充复合索引 (device_id, event_time)，其前缀 device_id
  也能覆盖单纯的按设备过滤 / 排序场景。

  本项目在 app/main.py 启动时用 Base.metadata.create_all 建表，而 create_all 只能创建
  "不存在的表"，不会给已存在的表补索引。因此：
    - 全新环境：模型已加 index=True / Index()，create_all 会自动建索引，无需本脚本。
    - 已有数据的环境：必须执行本脚本，用 ALTER TABLE ADD INDEX 补索引。

  本脚本幂等：先查 information_schema 判断索引是否已存在，不存在才创建，可重复执行。
  添加二级索引是 Online DDL（MySQL 8 / InnoDB 默认 INPLACE），一般不阻塞读写，但大表可能
  耗时较长，建议在低峰期执行，并提前对数据库做完整备份。


用法：
  python migrate_add_time_index.py            # 预检：打印各索引是否存在（不改动数据库）
  python migrate_add_time_index.py --apply    # 执行：仅缺失的索引会被创建
"""
import asyncio
import sys

from sqlalchemy import text

from app.database import async_session


# 每张表要补的索引：(索引名, 列定义SQL)
INDEXES = {
    "iot_process_log": [
        ("ix_iot_process_log_event_time", "event_time"),
        ("ix_iot_process_log_device_time", "device_id, event_time"),
    ],
    "iot_flatness_data": [
        ("ix_iot_flatness_event_time", "event_time"),
        ("ix_iot_flatness_device_time", "device_id, event_time"),
    ],
}


async def index_exists(db, table: str, index: str) -> bool:
    row = await db.execute(
        text(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :tbl AND index_name = :idx LIMIT 1"
        ),
        {"tbl": table, "idx": index},
    )
    return row.first() is not None


async def add_index(db, table: str, index: str, cols: str):
    await db.execute(text(f"ALTER TABLE `{table}` ADD INDEX `{index}` ({cols})"))
    await db.commit()


async def main():
    apply = "--apply" in sys.argv
    print("=" * 60)
    print("为 iot_process_log / iot_flatness_data 补时间索引")
    print("=" * 60)
    print(f"模式: {'执行 (--apply)' if apply else '预检（仅检查，不改数据库）'}")
    print("-" * 60)

    async with async_session() as db:
        for table, idxs in INDEXES.items():
            for idx, cols in idxs:
                exists = await index_exists(db, table, idx)
                if exists:
                    print(f"  [已存在] {table}.{idx} ({cols})")
                    continue
                if apply:
                    try:
                        await add_index(db, table, idx, cols)
                        print(f"  [已创建] {table}.{idx} ({cols})")
                    except Exception as e:  # noqa: BLE001
                        await db.rollback()
                        print(f"  [失败]   {table}.{idx}: {e}")
                else:
                    print(f"  [缺失]   {table}.{idx} ({cols})  → 需执行 --apply 创建")

    print("-" * 60)
    if not apply:
        print("以上为预检结果。确认无误后运行：python migrate_add_time_index.py --apply")


if __name__ == "__main__":
    asyncio.run(main())
