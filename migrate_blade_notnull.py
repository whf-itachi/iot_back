"""迁移脚本：将 iot_process_log / iot_flatness_data 的 blade_id 改为 NOT NULL，并可选去重。

背景：
  之前重复上传 + 入库时 blade_id 允许为空，导致两表残留大量 blade_id 为 NULL 的行，
  唯一索引对 (device_id, NULL) 不生效，去重脚本也主动排除了 NULL 行，因此清不干净。
  现在写入逻辑已加守卫（device_id / blade_id 为空直接跳过），模型也将 blade_id 改为
  NOT NULL。但 create_all 不会修改已存在的表，必须手动 ALTER，且 ALTER 前需先清理 NULL 行。

两个相互独立的可选步骤：
  A. NOT NULL 迁移（--force 触发）
     删除 blade_id 为 NULL 的历史行，再把 blade_id 列改为 NOT NULL。
  B. 历史去重（--dedup 触发，需配合 --force 才真正删除）
     按 (device_id, blade_id)             —— iot_process_log
        (device_id, blade_id, process_stage) —— iot_flatness_data
     分组，每组保留 id 最大（最新插入）的一条，删除其余重复行。
     注意：只处理三组键均非 NULL 的组；NULL 的 blade_id 行由步骤 A 负责，不去重。

⚠️ 重要：
  1) 运行前请务必对数据库做完整备份！本脚本会删除数据 / 修改表结构。
  2) 默认只做"预检"（统计 + 打印），不会删除也不会 ALTER。
  3) 确认无误后，加 --force 才真正执行删除 + 加 NOT NULL。
  4) 去重是独立步骤：--dedup 仅预检；--dedup --force 才真正删除重复行。

用法：
  python migrate_blade_notnull.py                 # 预检：统计 NULL 行（不动数据）
  python migrate_blade_notnull.py --dedup         # 预检：额外统计重复行（不动数据）
  python migrate_blade_notnull.py --force         # 执行：清理 NULL 行 + ALTER NOT NULL
  python migrate_blade_notnull.py --dedup --force # 执行：清理 NULL 行 + 去重 + ALTER NOT NULL
"""
import asyncio
import sys

from sqlalchemy import text

from app.database import engine, async_session


TABLES = ["iot_process_log", "iot_flatness_data"]

# 每张表的去重分组键（唯一约束列）。平面度额外含 process_stage。
DEDUP_KEYS = {
    "iot_process_log": ["device_id", "blade_id"],
    "iot_flatness_data": ["device_id", "blade_id", "process_stage"],
}


async def count_null_blade(db) -> dict:
    result = {}
    for tbl in TABLES:
        row = await db.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE blade_id IS NULL"))
        result[tbl] = row.scalar() or 0
    return result


async def delete_null_blade(db) -> dict:
    result = {}
    for tbl in TABLES:
        n = await db.execute(text(f"DELETE FROM {tbl} WHERE blade_id IS NULL"))
        result[tbl] = n.rowcount
    await db.commit()
    return result


async def alter_not_null(db) -> dict:
    result = {}
    for tbl in TABLES:
        try:
            await db.execute(text(
                f"ALTER TABLE {tbl} MODIFY COLUMN blade_id VARCHAR(100) NOT NULL COMMENT '叶片编号'"
            ))
            await db.commit()
            result[tbl] = "OK"
        except Exception as e:
            await db.rollback()
            result[tbl] = f"失败: {e}"
    return result


def _keep_subquery(tbl: str, keys: list) -> str:
    """生成用于去重的 keep_id 子查询：每组保留 id 最大的一条。"""
    group_list = ", ".join(keys)
    return f"SELECT {group_list}, MAX(id) AS keep_id FROM {tbl} GROUP BY {group_list}"


def _dup_join_conds(keys: list) -> str:
    return " AND ".join(f"t.{c} = k.{c}" for c in keys)


def _not_null_conds(keys: list) -> str:
    return " AND ".join(f"t.{c} IS NOT NULL" for c in keys)


async def count_dup(db) -> dict:
    """统计每张表将删除的重复行数（仅预检，不删除）。"""
    result = {}
    for tbl in TABLES:
        keys = DEDUP_KEYS[tbl]
        keep_sub = _keep_subquery(tbl, keys)
        join = _dup_join_conds(keys)
        not_null = _not_null_conds(keys)
        sql = text(
            f"SELECT COUNT(*) FROM {tbl} t "
            f"LEFT JOIN ({keep_sub}) k ON {join} AND t.id = k.keep_id "
            f"WHERE k.keep_id IS NULL AND {not_null}"
        )
        row = await db.execute(sql)
        result[tbl] = row.scalar() or 0
    return result


async def delete_dup(db) -> dict:
    """删除每组中 id 非最大（即非最新插入）的重复行，保留 keep_id 那一条。"""
    result = {}
    for tbl in TABLES:
        keys = DEDUP_KEYS[tbl]
        keep_sub = _keep_subquery(tbl, keys)
        join = _dup_join_conds(keys)
        not_null = _not_null_conds(keys)
        sql = text(
            f"DELETE t FROM {tbl} t "
            f"LEFT JOIN ({keep_sub}) k ON {join} AND t.id = k.keep_id "
            f"WHERE k.keep_id IS NULL AND {not_null}"
        )
        n = await db.execute(sql)
        await db.commit()
        result[tbl] = n.rowcount
    return result


async def main():
    force = "--force" in sys.argv
    dedup = "--dedup" in sys.argv

    print("=" * 60)
    print("blade_id NOT NULL 迁移 + 历史去重脚本")
    print("=" * 60)
    print("⚠️  运行前请确认已对数据库做完整备份！")
    print(f"模式: {'强制执行 (--force)' if force else '预检（仅统计，不改动数据）'}")
    print(f"去重: {'是 (--dedup)' if dedup else '否'}")
    print("-" * 60)

    async with async_session() as db:
        # ---------- 步骤 A 预检：NULL 统计 ----------
        null_counts = await count_null_blade(db)
        total_null = sum(null_counts.values())
        print("[步骤A] blade_id 为 NULL 的行数：")
        for tbl in TABLES:
            print(f"  {tbl}: {null_counts[tbl]}")
        print("-" * 60)

        # ---------- 步骤 B 预检：重复行统计 ----------
        if dedup:
            dup_counts = await count_dup(db)
            total_dup = sum(dup_counts.values())
            print("[步骤B] 重复行数（每组保留 id 最大一条，其余将被删除）：")
            for tbl in TABLES:
                keys = DEDUP_KEYS[tbl]
                print(f"  {tbl}: 按 ({', '.join(keys)}) 重复 {dup_counts[tbl]} 行")
            print("-" * 60)
        else:
            total_dup = 0

        # ---------- 未加 --force：仅预检，结束 ----------
        if not force:
            if total_null > 0:
                print(f"\n当前为预检模式，未做任何修改。")
                print(f"共 {total_null} 行 blade_id 为 NULL。执行以下命令清理并加 NOT NULL：")
                print("    python migrate_blade_notnull.py --force")
            if dedup:
                print("\n去重为预检（--dedup 未配合 --force）：")
                if total_dup > 0:
                    print(f"共 {total_dup} 行重复。需加 --force 才会真正删除：")
                    print("    python migrate_blade_notnull.py --dedup --force")
                else:
                    print("未发现重复行，无需删除。")
            if total_null == 0 and (not dedup or total_dup == 0):
                print("\n未发现需处理的数据，可直接执行 --force 将 blade_id 设为 NOT NULL（无数据会被删除）。")
            return

        # ---------- 强制执行 ----------
        # 1) 清理 NULL 行
        if total_null > 0:
            print(f"\n[步骤A-1/3] 删除 {total_null} 行 blade_id 为 NULL 的历史数据 ...")
            deleted = await delete_null_blade(db)
            for tbl in TABLES:
                print(f"      {tbl}: 删除 {deleted[tbl]} 行")
        else:
            print("\n[步骤A-1/3] 无 NULL 行需删除，跳过。")

        # 2) 去重删除（若 --dedup）
        if dedup:
            dup_before = await count_dup(db)
            total_dup_before = sum(dup_before.values())
            if total_dup_before > 0:
                print(f"\n[步骤B-2/3] 删除 {total_dup_before} 行重复数据（每组保留最新一条）...")
                deleted = await delete_dup(db)
                for tbl in TABLES:
                    print(f"      {tbl}: 删除 {deleted[tbl]} 行")
                after = await count_dup(db)
                for tbl in TABLES:
                    print(f"      {tbl}: 剩余重复 {after[tbl]} 行")
            else:
                print("\n[步骤B-2/3] 无重复行需删除，跳过。")
        else:
            print("\n[步骤B-2/3] 未启用 --dedup，跳过去重。")

        # 3) ALTER NOT NULL
        print("\n[步骤A-3/3] ALTER TABLE 将 blade_id 改为 NOT NULL ...")
        altered = await alter_not_null(db)
        for tbl in TABLES:
            print(f"      {tbl}: {altered[tbl]}")

        print("\n迁移完成。建议重启后端服务以使模型变更与新建连接生效。")


if __name__ == "__main__":
    asyncio.run(main())
