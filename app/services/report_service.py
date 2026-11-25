"""报表聚合查询服务 — 统计报表（加工统计 / OEE / 型号统计 / 报警Top10）

所有查询都强制走调用方传入的 `allowed_ids`（登录用户可访问的设备集合），
确保数据隔离铁律：用户只能看到自己/下级设备的报表数据。

合格标准：after_flatness <= 0.5（与 Dashboard / MEMORY 一致）。
OEE 口径：占用时长=加工结束时间-加工开始时间（含工序间隙，区别于净加工时长 total_duration）；
可用率=加工占用总时长/(有生产天数×计划工时)，性能率=理论节拍×片数/加工占用总时长，
质量率=合格片数/总片数，OEE=三者乘积。计划工时(默认8h/天)与理论节拍(默认平均占用时长)
均可由调用方传入覆盖（详见 query_oee_statistics）。
报警统计口径：仅统计非空 alarm_content 的告警记录（空内容=恢复，不计）。
报警字符串拆分：alarm_content 为多条故障单行字符串，以 ' - '（横杠两侧带空格）
连接；为兼容历史数据亦兼容裸 '-'，统一按「空白+横杠+空白」拆分。
"""
import re
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.iot_event import IotProcessLog, IotAlarm
from ..models.device import IotDevice

# 合格率阈值（mm）
QUALIFY_THRESHOLD = 0.5

# OEE 可用率口径：有生产的天 × 每天计划工时（用户确认：单班 8h）
PLANNED_HOURS_PER_PRODUCTIVE_DAY = 8
MINUTES_PER_HOUR = 60


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
# 2) 设备 OEE 报告（可用率 × 性能率 × 合格率 三维度）
# ----------------------------------------------------------------------------
# 计算口径（依据用户确认，风力发电叶片加工行业通用 OEE 定义简化实现）：
#   占用时长 = process_end_time − process_start_time（毫秒→分钟），含工序间隙；
#            区别于设备上报的净加工时长 total_duration（实测约小 13.6%）。
#   可用率 Availability = 加工占用总时长 ÷ (有生产天数 × 计划生产时长)
#                       （有生产天数 = 本机有加工记录的日期去重数；
#                        计划生产时长默认 8h/天，可由客户按行业/生产计划手动输入）
#   性能率 Performance = 理论节拍 × 加工片数 ÷ 加工占用总时长
#                      （理论节拍默认 = 样本平均占用时长，此时性能率恒为 100%；
#                        可由客户按生产计划手动输入标准节拍，使指标有区分度）
#   质量率 Quality     = 合格片数 ÷ 总加工片数（after_flatness ≤ 0.5mm）
#   OEE               = 可用率 × 性能率 × 质量率
# 说明：本地库无「排班/计划停机/开机状态」数据，可用率按"有生产日×计划工时"作为
#      计划生产时间；无预置「理论节拍」配置，默认取平均占用时长作为基准。
#      两个参数均为全局值，由调用方（页面筛选栏）传入，缺省时回退默认值。
# 所有比率钳制在 [0, 1]，避免出现 >100% 的异常值。
# ----------------------------------------------------------------------------

def _clamp_rate(v: float | None) -> float | None:
    if v is None:
        return None
    return round(min(1.0, max(0.0, v)), 4)


def _occupancy_minutes(r: IotProcessLog) -> float | None:
    """单片叶片的加工占用时长（分钟）= 加工结束时间 − 加工开始时间。

    process_start_time / process_end_time 均为毫秒时间戳，含工序间隙（换刀、
    装夹、等待测量等）；区别于设备上报的净加工时长 total_duration。
    起止时间缺失或结束不晚于开始时返回 None，视为无效记录。
    """
    s, e = r.process_start_time, r.process_end_time
    if s is None or e is None or e <= s:
        return None
    return (e - s) / 60000.0


def _productive_days(rows: list[IotProcessLog]) -> int:
    """有生产天数：按加工日志的 event_time 取本地日历日去重。

    一台设备在某天有加工记录即算一个生产日；多设备同一天各自计（设备·天），
    与"按真实 device_id 区分"的铁律一致。event_time 为毫秒时间戳。
    """
    days: set[tuple[str, object]] = set()
    for r in rows:
        if r.event_time is None:
            continue
        day = datetime.fromtimestamp(r.event_time / 1000).date()
        days.add((r.device_id, day))
    return len(days)


def _compute_oee_factors(
    durations: list[float],
    productive_days: int,
    qualified: int,
    total: int,
    planned_hours: float | None = None,
    ideal_cycle: float | None = None,
) -> dict:
    """根据一组加工占用时长计算 OEE 三维度。durations 单位为分钟。

    planned_hours: 每天计划生产工时，缺省/非法时回退默认 8h。
    ideal_cycle:   理论节拍(分钟/片)，缺省/非法时取样本平均占用时长。
    """
    total_duration = sum(durations) if durations else 0
    valid_count = len(durations)
    avg_cycle = total_duration / valid_count if valid_count else None  # 平均占用时长

    # 计划生产时长：客户输入优先，非法时回退默认 8h
    hours = planned_hours if (planned_hours is not None and planned_hours > 0) else PLANNED_HOURS_PER_PRODUCTIVE_DAY
    planned_minutes = productive_days * hours * MINUTES_PER_HOUR

    # 理论节拍：客户输入优先，否则用平均占用时长（此时性能率恒为 100%）
    ideal = ideal_cycle if (ideal_cycle is not None and ideal_cycle > 0) else avg_cycle

    availability = None
    if planned_minutes > 0 and total_duration > 0:
        availability = _clamp_rate(total_duration / planned_minutes)

    performance = None
    if ideal and total_duration > 0:
        performance = _clamp_rate((ideal * valid_count) / total_duration)

    quality = round(qualified / total, 4) if total else None
    availability = _clamp_rate(availability)
    performance = _clamp_rate(performance)
    oee = None
    if availability is not None and performance is not None and quality is not None:
        oee = round(availability * performance * quality, 4)

    return {
        "availability": availability,
        "performance": performance,
        "qualification_rate": quality,
        "oee": oee,
        "qualified": qualified,
        "total": total,
        "_total_duration": total_duration,
        "_ideal": ideal,
        "_avg_cycle": avg_cycle,
        "_planned_hours": hours,
        "_ideal_source": "custom" if (ideal_cycle is not None and ideal_cycle > 0) else "average",
        "_productive_days": productive_days,
        "_planned_minutes": planned_minutes,
    }


async def query_oee_statistics(
    db: AsyncSession,
    allowed_ids: set[str] | None,
    start_ms: int | None,
    end_ms: int | None,
    product: str | None = None,
    device_name: str | None = None,
    planned_hours: float | None = None,
    ideal_cycle: float | None = None,
) -> dict:
    proc = await query_processing_statistics(db, allowed_ids, start_ms, end_ms, product, device_name)

    # 重新解析设备范围并拉取加工明细，用于计算时长类指标（与加工统计保持同一口径）
    dev_ids = await _resolve_device_ids(db, product, allowed_ids)
    dev_ids = await _device_ids_for_name(db, device_name, dev_ids)
    if dev_ids is not None and not dev_ids:
        blades: list[IotProcessLog] = []
    else:
        blades = await _fetch_process_logs(db, dev_ids, start_ms, end_ms)

    # 有生产天数：按 (device_id, 本地日期) 去重，多设备同一天各自计
    all_durations = [
        d for d in (_occupancy_minutes(r) for r in blades) if d is not None
    ]
    device_count = len({r.device_id for r in blades})
    productive_days = _productive_days(blades)
    overall = _compute_oee_factors(
        all_durations, productive_days,
        proc["qualified"], proc["total_blades"],
        planned_hours, ideal_cycle,
    )

    # 分设备：按设备名聚合（与加工统计 per_device 展示一致），有生产天数按该组真实记录计
    groups: dict[str, dict] = {}
    for r in blades:
        key = r.device_name or r.device_id or "未知设备"
        g = groups.setdefault(key, {"rows": [], "durations": [], "total": 0, "qualified": 0})
        g["rows"].append(r)
        g["total"] += 1
        if _is_qualified(r):
            g["qualified"] += 1
        d = _occupancy_minutes(r)
        if d is not None:
            g["durations"].append(d)

    per_device = []
    for name, g in groups.items():
        f = _compute_oee_factors(
            g["durations"], _productive_days(g["rows"]), g["qualified"], g["total"],
            planned_hours, ideal_cycle,
        )
        per_device.append({
            "device_name": name,
            "total": f["total"],
            "qualified": f["qualified"],
            "availability": f["availability"],
            "performance": f["performance"],
            "qualification_rate": f["qualification_rate"],
            "oee": f["oee"],
        })
    per_device.sort(key=lambda x: (-x["total"], x["device_name"]))

    hours = overall["_planned_hours"]
    ideal_src = overall["_ideal_source"]
    formula = {
        "availability": f"加工占用总时长 ÷ (有生产天数 × {hours:g}h)（占用时长 = 加工结束时间 − 加工开始时间；有生产天数 = 有加工记录的日期数，按设备分别计；计划工时默认8h可手动修改）",
        "performance": f"理论节拍 × 加工片数 ÷ 加工占用总时长（理论节拍{'取客户输入值' if ideal_src == 'custom' else '取样本平均占用时长（默认100%可手动修改）'}）",
        "quality": "合格片数 ÷ 总加工片数（平面度 ≤ 0.5mm）",
        "oee": "可用率 × 性能率 × 质量率",
    }
    return {
        "overall": {
            "availability": overall["availability"],
            "performance": overall["performance"],
            "qualification_rate": overall["qualification_rate"],
            "qualified": overall["qualified"],
            "total": overall["total"],
            "oee": overall["oee"],
        },
        "per_device": per_device,
        "range": proc["range"],
        "formula": formula,
        "productive_days": productive_days,
        "planned_hours": hours,
        "planned_minutes": overall["_planned_minutes"],
        "device_count": device_count,
        "total_duration_minutes": round(overall["_total_duration"], 1),
        "ideal_cycle_minutes": round(overall["_ideal"], 1) if overall["_ideal"] is not None else None,
        "auto_cycle_minutes": round(overall["_avg_cycle"], 1) if overall["_avg_cycle"] is not None else None,
        "ideal_cycle_source": ideal_src,
        "note": f"占用时长=加工结束−加工开始(含工序间隙)；可用率=占用总时长÷(有生产天数×{hours:g}h)，性能率理论节拍={overall['_ideal']:.1f}分钟({ideal_src})，均来自本地加工日志"
               if overall["_ideal"] is not None else "所选范围内无有效加工时长数据",
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
