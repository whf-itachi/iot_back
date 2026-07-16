"""一次性数据迁移：清理重复数据 + 添加唯一约束（按 device_id + blade_id 联合去重）。

使用方法：
    cd iot_back
    python migrate_dedup.py

执行前请先确保数据库服务正常运行，建议先备份数据。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import async_session


async def migrate():
    async with async_session() as db:
        # ========================
        # 1. iot_flatness_data：按 (device_id, blade_id, process_stage) 去重
        # ========================
        print("[1/4] 清理 iot_flatness_data 重复数据 ...")
        result = await db.execute(text("""
            SELECT COUNT(*) as cnt FROM iot_flatness_data
        """))
        total = result.scalar()
        print(f"      当前总记录数: {total}")

        result = await db.execute(text("""
            DELETE t1 FROM iot_flatness_data t1
            JOIN (
                SELECT device_id, blade_id, process_stage, MAX(id) AS max_id
                FROM iot_flatness_data
                WHERE blade_id IS NOT NULL
                GROUP BY device_id, blade_id, process_stage
                HAVING COUNT(*) > 1
            ) t2 ON t1.device_id = t2.device_id
                AND t1.blade_id = t2.blade_id
                AND t1.process_stage = t2.process_stage
                AND t1.id < t2.max_id
        """))
        deleted = result.rowcount
        print(f"      删除重复记录: {deleted} 条")

        # ========================
        # 2. iot_process_log：按 (device_id, blade_id) 去重
        # ========================
        print("[2/4] 清理 iot_process_log 重复数据 ...")
        result = await db.execute(text("""
            SELECT COUNT(*) as cnt FROM iot_process_log
        """))
        total = result.scalar()
        print(f"      当前总记录数: {total}")

        result = await db.execute(text("""
            DELETE t1 FROM iot_process_log t1
            JOIN (
                SELECT device_id, blade_id, MAX(id) AS max_id
                FROM iot_process_log
                WHERE blade_id IS NOT NULL
                GROUP BY device_id, blade_id
                HAVING COUNT(*) > 1
            ) t2 ON t1.device_id = t2.device_id
                AND t1.blade_id = t2.blade_id
                AND t1.id < t2.max_id
        """))
        deleted = result.rowcount
        print(f"      删除重复记录: {deleted} 条")

        # ========================
        # 3. 删除旧索引，创建新唯一索引
        # ========================
        print("[3/4] 更新唯一索引 ...")

        # 删除旧索引（如果存在）
        for old_idx, table in [
            ("uq_flatness_blade_stage", "iot_flatness_data"),
            ("uq_process_log_blade_id", "iot_process_log"),
        ]:
            try:
                await db.execute(text(f"DROP INDEX {old_idx} ON {table}"))
                print(f"      ✓ 已删除旧索引 {old_idx}")
            except Exception:
                print(f"      - 旧索引 {old_idx} 不存在，跳过")

        # 创建新索引
        for idx_name, table, columns in [
            ("uq_flatness_device_blade_stage", "iot_flatness_data",
             "device_id, blade_id, process_stage"),
            ("uq_process_log_device_blade", "iot_process_log",
             "device_id, blade_id"),
        ]:
            try:
                await db.execute(text(
                    f"CREATE UNIQUE INDEX {idx_name} ON {table} ({columns})"
                ))
                print(f"      ✓ {idx_name} 已创建")
            except Exception as e:
                if "Duplicate" in str(e) or "already exists" in str(e):
                    print(f"      - {idx_name} 已存在，跳过")
                else:
                    print(f"      ✗ 创建失败: {e}")

        # ========================
        # 4. 提交
        # ========================
        await db.commit()
        print("[4/4] 迁移完成！")


if __name__ == "__main__":
    asyncio.run(migrate())
