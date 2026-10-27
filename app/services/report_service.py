"""报表聚合查询服务 — 统计报表（加工统计 / OEE / 型号统计 / 报警Top10）

所有查询都强制走调用方传入的 `allowed_ids`（登录用户可访问的设备集合），
确保数据隔离铁律：用户只能看到自己/下级设备的报表数据。

合格标准：after_flatness <= 0.5（与 Dashboard / MEMORY 一致）。
报警统计口径：仅统计非空 alarm_content 的告警记录（空内容=恢复，不计）。
报警字符串拆分：alarm_content 为多条故障单行字符串，以 ' - '（横杠两侧带空格）
连接；为兼容历史数据亦兼容裸 '-'，统一按「空白+横杠+空白」拆分。
"""
import re
from collections import Counter

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.iot_event import IotProcessLog, IotAlarm
from ..models.device import IotDevice

# 合格率阈值（mm）
QUALIFY_THRESHOLD = 0.5


# ----------------------------------------------------------------------------
# 设备过滤解析
# ----------------------------------------------------------------------------

async def _resolve_device_ids(
    db: AsyncSession,
    product: str | None,
    allowed_ids: set[str] | None,
) -> set[str] | None:
    """解析设备过滤集合。

    返回：
      - None           ：不做设备过滤（allowed_ids 为 None 且未指定产品）
      - 空 set()       ：无任何设备命中（直接返回空结果）
      - 非空 set()     ：需过滤的设备 ID 集合（产品 ∩ 可访问设备）
    """
    if product:
        stmt = select(IotDevice.id).where(
            func.lower(IotDevice.product_name) == product.strip().lower()
        )
        if allowed_ids is not None:
            if not allowed_ids:
                return set()
            stmt = stmt.where(IotDevice.id.in_(allowed_ids))
        res = await db.execute(stmt)
        return {r[0] for r in res.all()}
    return allowed_ids


async def _device_ids_for_name(
    db: AsyncSession,
    device_name: str | None,
    base_ids: set[str] | None,
) -> set[str] | None:
    """根据设备名称解析其设备 ID，并与 base_ids（产品/可访问范围）取交集。

    用于告警表（仅存 device_id）按设备名称过滤。
    """
    if not device_name:
        return base_ids
    stmt = select(IotDevice.id).where(IotDevice.name == device_name)
    res = await db.execute(stmt)
    ids = {r[0] for r in res.all()}
    if base_ids is not None:
        ids = {i for i in ids if i in base_ids}
    return ids


# ----------------------------------------------------------------------------
# 通用取数
# ----------------------------------------------------------------------------

async def _fetch_process_logs(
    db: AsyncSession,
    dev_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
) -> list[IotProcessLog]:
    """拉取加工日志（按 device_id 集合 + 时间范围过滤）。

    写入侧已对 (device_id, blade_id) 做 upsert（最新一条覆盖），存储层每个 (device, blade)
    恒为 1 行，无需读取时按 blade_id 去重。设备过滤统一通过 dev_ids（device_id 集合）下推。
    """
    conds = []
    if dev_ids is not None:
        conds.append(IotProcessLog.device_id.in_(dev_ids))
    if start_ms is not None:
        conds.append(IotProcessLog.event_time >= start_ms)
    if end_ms is not None:
        conds.append(IotProcessLog.event_time <= end_ms)

    stmt = select(IotProcessLog)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(desc(IotProcessLog.event_time), desc(IotProcessLog.id))
    return list((await db.execute(stmt)).scalars().all())


async def _count_alarms(
    db: AsyncSession,
    dev_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
    count_nonempty: bool = True,
) -> int:
    """统计告警条数。count_nonempty=True 时仅统计非空 alarm_content（排除恢复）。"""
    stmt = select(func.count(IotAlarm.id))
    conds = []
    if dev_ids is not None:
        conds.append(IotAlarm.device_id.in_(dev_ids))
    if start_ms is not None:
        conds.append(IotAlarm.alarm_time >= start_ms)
    if end_ms is not None:
        conds.append(IotAlarm.alarm_time <= end_ms)

    if count_nonempty:
        conds.append(IotAlarm.alarm_content != "")
    if conds:
        stmt = stmt.where(and_(*conds))
    return (await db.execute(stmt)).scalar() or 0


def _is_qualified(r: IotProcessLog) -> bool:
    return r.after_flatness is not None and r.after_flatness <= QUALIFY_THRESHOLD


def _avg(vals) -> float | None:
    cleaned = [v for v in vals if v is not None and v != 0]
    if not cleaned:
        return None
    return round(sum(cleaned) / len(cleaned), 4)


def _build_per_device(blades: list[IotProcessLog]) -> list[dict]:
    """按设备名称聚合：叶片数 / 合格数 / 合格率。"""
    agg: dict[str, dict] = {}
    for r in blades:
        key = r.device_name or r.device_id or "未知设备"
        g = agg.setdefault(key, {"total": 0, "qualified": 0})
        g["total"] += 1
        if _is_qualified(r):
            g["qualified"] += 1
    result = []
    for name, g in agg.items():
        result.append({
            "device_name": name,
            "total": g["total"],
            "qualified": g["qualified"],
            "qualification_rate": round(g["qualified"] / g["total"], 4) if g["total"] else None,
        })
    result.sort(key=lambda x: (-x["total"], x["device_name"]))
    return result


# ----------------------------------------------------------------------------
# 1) 加工统计报表（合格率 + 报警统计 + OEE合格率维度）
# ----------------------------------------------------------------------------

async def query_processing_statistics(
    db: AsyncSession,
    allowed_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
    product: str | None = None,
    device_name: str | None = None,
) -> dict:
    dev_ids = await _resolve_device_ids(db, product, allowed_ids)
    # 把设备名解析为 device_id 并入 dev_ids，统一按 device_id 过滤（不再按 device_name 过滤）
    dev_ids = await _device_ids_for_name(db, device_name, dev_ids)
    if dev_ids is not None and not dev_ids:
        return _empty_processing()

    blades = await _fetch_process_logs(db, dev_ids, start_ms, end_ms)
    total = len(blades)
    qualified = sum(1 for r in blades if _is_qualified(r))
    qual_rate = round(qualified / total, 4) if total else None
    avg_after = _avg([r.after_flatness for r in blades])
    avg_total = _avg([r.total_duration for r in blades])  # 单位：分钟

    # 报警统计：与加工日志同一时间/设备范围，仅非空内容（dev_ids 已含设备名解析结果）
    alarm_count = await _count_alarms(db, dev_ids, start_ms, end_ms, count_nonempty=True)

    return {
        "total_blades": total,
        "qualified": qualified,
        "qualification_rate": qual_rate,
        "avg_after_flatness": avg_after,
        "avg_total_duration": avg_total,
        "alarm_count": alarm_count,
        # OEE 本期仅合格率维度，可用率/性能率待采集
        "oee": {
            "availability": None,
            "performance": None,
            "qualification_rate": qual_rate,
            "oee": None,
            "note": "本期仅实现合格率维度，可用率与性能率待数据采集后补充",
        },
        "per_device": _build_per_device(blades),
        "range": {"start": start_ms, "end": end_ms},
    }


def _empty_processing() -> dict:
    return {
        "total_blades": 0,
        "qualified": 0,
        "qualification_rate": None,
        "avg_after_flatness": None,
        "avg_total_duration": None,
        "alarm_count": 0,
        "oee": {"availability": None, "performance": None, "qualification_rate": None,
                "oee": None, "note": "无数据"},
        "per_device": [],
        "range": {"start": None, "end": None},
    }


# ----------------------------------------------------------------------------
# 2) 设备 OEE 报告（可用率 × 性能率 × 合格率 三维度；本期仅合格率）
# ----------------------------------------------------------------------------

async def query_oee_statistics(
    db: AsyncSession,
    allowed_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
    product: str | None = None,
    device_name: str | None = None,
) -> dict:
    proc = await query_processing_statistics(db, allowed_ids, start_ms, end_ms, product, device_name)
    overall = {
        "availability": None,
        "performance": None,
        "qualification_rate": proc["qualification_rate"],
        "qualified": proc["qualified"],
        "total": proc["total_blades"],
        "oee": None,
    }
    per_device = [
        {
            "device_name": d["device_name"],
            "total": d["total"],
            "qualified": d["qualified"],
            "availability": None,
            "performance": None,
            "qualification_rate": d["qualification_rate"],
            "oee": None,
        }
        for d in proc["per_device"]
    ]
    return {
        "overall": overall,
        "per_device": per_device,
        "range": proc["range"],
        "note": "本期仅实现合格率维度，可用率与性能率待数据采集后补充",
    }


# ----------------------------------------------------------------------------
# 3) 型号统计报表（按 blade_id 前 3 位分组）
# ----------------------------------------------------------------------------

async def query_model_statistics(
    db: AsyncSession,
    allowed_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
    product: str | None = None,
    device_name: str | None = None,
) -> list[dict]:
    dev_ids = await _resolve_device_ids(db, product, allowed_ids)
    # 把设备名解析为 device_id 并入 dev_ids，统一按 device_id 过滤（不再按 device_name 过滤）
    dev_ids = await _device_ids_for_name(db, device_name, dev_ids)
    if dev_ids is not None and not dev_ids:
        return []

    blades = await _fetch_process_logs(db, dev_ids, start_ms, end_ms)
    groups: dict[str, dict] = {}
    for r in blades:
        bid = (r.blade_id or "").strip()
        model = bid[:3] if bid else "未知"
        g = groups.setdefault(model, {"total": 0, "qualified": 0, "after": []})
        g["total"] += 1
        if _is_qualified(r):
            g["qualified"] += 1
        if r.after_flatness is not None:
            g["after"].append(r.after_flatness)

    result = []
    for model, g in groups.items():
        result.append({
            "model": model,
            "total": g["total"],
            "qualified": g["qualified"],
            "qualification_rate": round(g["qualified"] / g["total"], 4) if g["total"] else None,
            "avg_after_flatness": round(sum(g["after"]) / len(g["after"]), 4) if g["after"] else None,
        })
    result.sort(key=lambda x: (-x["total"], x["model"]))
    return result


# ----------------------------------------------------------------------------
# 4) 报警频次 Top10 分析报告
# ----------------------------------------------------------------------------

async def query_alarm_top(
    db: AsyncSession,
    allowed_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
    product: str | None = None,
    device_name: str | None = None,
    top: int = 10,
) -> dict:
    dev_ids = await _resolve_device_ids(db, product, allowed_ids)
    if dev_ids is not None and not dev_ids:
        return {"items": [], "total_records": 0, "distinct_faults": 0}

    alarm_dev_ids = await _device_ids_for_name(db, device_name, dev_ids)
    if alarm_dev_ids is not None and not alarm_dev_ids:
        return {"items": [], "total_records": 0, "distinct_faults": 0}

    stmt = select(IotAlarm)
    conds = []
    if alarm_dev_ids is not None:
        conds.append(IotAlarm.device_id.in_(alarm_dev_ids))
    if start_ms is not None:
        conds.append(IotAlarm.alarm_time >= start_ms)
    if end_ms is not None:
        conds.append(IotAlarm.alarm_time <= end_ms)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(desc(IotAlarm.alarm_time), desc(IotAlarm.id))
    rows = (await db.execute(stmt)).scalars().all()

    counter: Counter = Counter()
    total_records = 0
    for r in rows:
        content = (r.alarm_content or "").strip()
        if not content:
            continue  # 空内容 = 告警恢复，跳过
        total_records += 1
        # 以 ' - ' 连接，兼容裸 '-'：用 \s*-\s* 拆分
        for part in re.split(r"\s*-\s*", content):
            p = part.strip()
            if p:
                counter[p] += 1

    items = [{"fault": fault, "count": cnt} for fault, cnt in counter.most_common(top)]
    return {
        "items": items,
        "total_records": total_records,
        "distinct_faults": len(counter),
    }
