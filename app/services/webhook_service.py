"""Webhook 事件处理服务 — 按事件类型写入对应表"""
import json
import re
from datetime import datetime
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.iot_event import IotWebhookLog, IotProcessLog, IotFlatnessData
from ..utils.logger import logger


async def save_event(
    db: AsyncSession,
    device_id: str,
    device_name: str,
    event_type: str,
    timestamp: int,
    data: dict,
    raw_body: str = "",
):
    """根据事件类型保存到对应的表中，同时记录推送日志"""
    logger.info(f"[save_event] 开始处理 event_type={event_type}, device_id={device_id}, blade_id={data.get('blade_id', '')}")

    # 记录推送日志（所有类型都记）
    save_webhook_log(db, device_id, device_name, event_type, timestamp, raw_body)
    logger.debug(f"[save_event] webhook 推送日志已加入会话")

    try:
        if event_type == "process_log_report":
            result = await _save_process_log(db, device_id, device_name, timestamp, data)
        elif event_type == "flatness_data":
            result = await _save_flatness_data(db, device_id, device_name, timestamp, data)
        else:
            # 未知类型只记日志，不写入业务表
            logger.warning(f"[save_event] 未知事件类型: {event_type}，仅记录推送日志")
            await db.commit()
            return None

        logger.info(f"[save_event] 写入成功 event_type={event_type}, id={result.id}")
        return result
    except Exception as e:
        logger.error(f"[save_event] 写入数据库失败 event_type={event_type}, device_id={device_id}: {e}", exc_info=True)
        raise


def save_webhook_log(db: AsyncSession, device_id: str, device_name: str, event_type: str, timestamp: int, raw_body: str):
    log = IotWebhookLog(
        device_id=device_id,
        device_name=device_name or "",
        event_type=event_type,
        event_time=timestamp,
        raw_body=raw_body,
    )
    db.add(log)


# ============================ 工具函数 ============================

# 匹配 "2026-05-13 00:18:07" 或 "2026-05-13T00:18:07" 格式
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _parse_datetime_to_ms(v: str) -> int:
    """将 '2026-05-13 00:18:07' 或 '2026-05-13T00:18:07' 转为毫秒时间戳，失败返回 0"""
    try:
        v = v.replace("T", " ")
        dt = datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _int(d: dict, key: str) -> int | None:
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        # 尝试直接转整数（纯数字字符串）
        try:
            return int(v)
        except ValueError:
            pass
        # 尝试日期时间字符串 → 毫秒时间戳
        if _DATETIME_RE.match(v):
            return _parse_datetime_to_ms(v)
        # 尝试 float 字符串
        try:
            return int(float(v))
        except ValueError:
            logger.warning(f"[_int] 无法转换字段 '{key}' 的值: {v!r}")
            return None
    return None


def _float(d: dict, key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            logger.warning(f"[_float] 无法转换字段 '{key}' 的值: {v!r}")
            return None
    return None


def _str(d: dict, key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    return str(v) if v else None


async def _save_process_log(db: AsyncSession, device_id: str, device_name: str, timestamp: int, data: dict):
    blade_id = _str(data, "blade_id")
    logger.info(f"[_save_process_log] 准备写入: blade_id={blade_id}, device={device_name}")

    log = IotProcessLog(
        device_id=device_id,
        device_name=device_name or "",
        event_time=timestamp,

        blade_id=blade_id,
        operator=_str(data, "operator"),
        process_start_time=_int(data, "process_start_time"),
        process_end_time=_int(data, "process_end_time"),
        total_duration=_int(data, "total_duration"),
        factory=_str(data, "factory"),
        device_type_code=_str(data, "device_type_code"),
        scan_result=_str(data, "scan_result"),
        bolt_sleeve_max=_float(data, "bolt_sleeve_max"),
        bolt_sleeve_min=_float(data, "bolt_sleeve_min"),
        pitch_angle=_float(data, "pitch_angle"),
        yaw_angle=_float(data, "yaw_angle"),
        bcd_estimate=_int(data, "bcd_estimate"),
        before_flatness=_float(data, "before_flatness"),
        mill_depth=_float(data, "mill_depth"),
        mill_cycles=_int(data, "mill_cycles"),
        mill_result=_str(data, "mill_result"),
        after_flatness=_float(data, "after_flatness"),
        adjust_leg_time=_int(data, "adjust_leg_time"),
        laser_adjust_time=_int(data, "laser_adjust_time"),
        rough_scan_time=_int(data, "rough_scan_time"),
        fine_scan_time=_int(data, "fine_scan_time"),
        mill_time=_int(data, "mill_time"),
        scan_report_time=_int(data, "scan_report_time"),
        upper_avg_power=_int(data, "upper_avg_power"),
        upper_max_power=_int(data, "upper_max_power"),
        lower_avg_power=_int(data, "lower_avg_power"),
        lower_max_power=_int(data, "lower_max_power"),
    )
    logger.debug(f"[_save_process_log] 模型构造完成，准备 commit")
    db.add(log)
    await db.commit()
    logger.info(f"[_save_process_log] 数据库写入成功: id={log.id}, blade_id={blade_id}")
    await db.refresh(log)
    return log


async def _save_flatness_data(db: AsyncSession, device_id: str, device_name: str, timestamp: int, data: dict):
    blade_id = _str(data, "blade_id")
    measure_time = _int(data, "measure_time")
    logger.info(f"[_save_flatness_data] 准备写入: blade_id={blade_id}, measure_time={measure_time}, device={device_name}")

    rec = IotFlatnessData(
        device_id=device_id,
        device_name=device_name or "",
        event_time=timestamp,

        measure_time=measure_time,
        blade_id=blade_id,
        max_value=_float(data, "max_value"),
        min_value=_float(data, "min_value"),
        pv_value=_float(data, "pv_value"),
        rms=_float(data, "rms"),
        hole_angle=data.get("hole_angle"),
        hole_value=data.get("hole_value"),
        process_stage=_str(data, "process_stage"),
    )
    logger.debug(f"[_save_flatness_data] 模型构造完成，准备 commit")
    db.add(rec)
    await db.commit()
    logger.info(f"[_save_flatness_data] 数据库写入成功: id={rec.id}, blade_id={blade_id}")
    await db.refresh(rec)
    return rec


# ============================ 查询 ============================

async def query_process_logs(
    db: AsyncSession,
    blade_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """从本地数据库查询加工日志"""
    stmt = select(IotProcessLog).order_by(desc(IotProcessLog.event_time), desc(IotProcessLog.id))
    if blade_id:
        stmt = stmt.where(IotProcessLog.blade_id.like(f"%{blade_id}%"))
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return [_process_log_to_dict(r) for r in result.scalars().all()]


async def query_flatness_data(
    db: AsyncSession,
    blade_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """从本地数据库查询平面度测量数据"""
    stmt = select(IotFlatnessData).order_by(desc(IotFlatnessData.event_time), desc(IotFlatnessData.id))
    if blade_id:
        stmt = stmt.where(IotFlatnessData.blade_id.like(f"%{blade_id}%"))
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return [_flatness_to_dict(r) for r in result.scalars().all()]


def _process_log_to_dict(r: IotProcessLog) -> dict:
    return {
        "_deviceId": r.device_id,
        "_deviceName": r.device_name,
        "_timestamp": r.event_time,
        "_logId": str(r.id),
        "blade_id": r.blade_id,
        "operator": r.operator,
        "process_start_time": r.process_start_time,
        "process_end_time": r.process_end_time,
        "total_duration": r.total_duration,
        "factory": r.factory,
        "device_type_code": r.device_type_code,
        "scan_result": r.scan_result,
        "bolt_sleeve_max": r.bolt_sleeve_max,
        "bolt_sleeve_min": r.bolt_sleeve_min,
        "pitch_angle": r.pitch_angle,
        "yaw_angle": r.yaw_angle,
        "bcd_estimate": r.bcd_estimate,
        "before_flatness": r.before_flatness,
        "mill_depth": r.mill_depth,
        "mill_cycles": r.mill_cycles,
        "mill_result": r.mill_result,
        "after_flatness": r.after_flatness,
        "adjust_leg_time": r.adjust_leg_time,
        "laser_adjust_time": r.laser_adjust_time,
        "rough_scan_time": r.rough_scan_time,
        "fine_scan_time": r.fine_scan_time,
        "mill_time": r.mill_time,
        "scan_report_time": r.scan_report_time,
        "upper_avg_power": r.upper_avg_power,
        "upper_max_power": r.upper_max_power,
        "lower_avg_power": r.lower_avg_power,
        "lower_max_power": r.lower_max_power,
    }


async def query_blade_list(
    db: AsyncSession,
    device_name: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """查询所有叶片及其加工前/后平面度数据（按设备名过滤）"""
    stmt = (
        select(IotFlatnessData)
        .order_by(desc(IotFlatnessData.event_time), desc(IotFlatnessData.id))
    )
    if device_name:
        stmt = stmt.where(IotFlatnessData.device_name == device_name)
    stmt = stmt.limit(limit * 2)  # 每个 blade 最多 2 条
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # 按 blade_id 分组，提取 before/after
    blade_map: dict[str, dict] = {}
    for r in rows:
        bid = r.blade_id or f"unknown_{r.id}"
        if bid not in blade_map:
            blade_map[bid] = {"blade_id": bid, "device_name": r.device_name}
        stage = r.process_stage or "before"
        if stage not in blade_map[bid]:
            blade_map[bid][stage] = _flatness_to_dict(r)

    # 按 blade_id 排序
    return sorted(blade_map.values(), key=lambda x: x["blade_id"])[:limit]


async def query_process_log_blades(
    db: AsyncSession,
    device_name: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """查询所有叶片的加工日志（按设备名过滤）"""
    stmt = (
        select(IotProcessLog)
        .order_by(desc(IotProcessLog.event_time), desc(IotProcessLog.id))
    )
    if device_name:
        stmt = stmt.where(IotProcessLog.device_name == device_name)
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    blades = []
    seen = set()
    for r in rows:
        bid = r.blade_id or f"unknown_{r.id}"
        if bid in seen:
            continue
        seen.add(bid)
        blades.append({
            "blade_id": bid,
            "device_name": r.device_name,
            "operator": r.operator,
            "mill_result": r.mill_result,
            "log": _process_log_to_dict(r),
        })
    return blades


def _flatness_to_dict(r: IotFlatnessData) -> dict:
    return {
        "_deviceId": r.device_id,
        "_deviceName": r.device_name,
        "_timestamp": r.event_time,
        "_logId": str(r.id),
        "measure_time": r.measure_time,
        "blade_id": r.blade_id,
        "max_value": r.max_value,
        "min_value": r.min_value,
        "pv_value": r.pv_value,
        "rms": r.rms,
        "hole_angle": r.hole_angle,
        "hole_value": r.hole_value,
        "process_stage": r.process_stage,
    }
