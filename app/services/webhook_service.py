"""Webhook 事件处理服务 — 按事件类型写入对应表"""
import json
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.iot_event import IotWebhookLog, IotProcessLog, IotFlatnessData


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

    # 记录推送日志（所有类型都记）
    save_webhook_log(db, device_id, device_name, event_type, timestamp, raw_body)

    if event_type == "process_log_report":
        return await _save_process_log(db, device_id, device_name, timestamp, data)
    elif event_type == "flatness_data":
        return await _save_flatness_data(db, device_id, device_name, timestamp, data)
    else:
        # 未知类型只记日志，不写入业务表
        return None


def save_webhook_log(db: AsyncSession, device_id: str, device_name: str, event_type: str, timestamp: int, raw_body: str):
    log = IotWebhookLog(
        device_id=device_id,
        device_name=device_name or "",
        event_type=event_type,
        event_time=timestamp,
        raw_body=raw_body,
    )
    db.add(log)


# ============================ 加工日志 ============================

def _int(d: dict, key: str) -> int | None:
    v = d.get(key)
    return int(v) if v is not None else None


def _float(d: dict, key: str) -> float | None:
    v = d.get(key)
    return float(v) if v is not None else None


def _str(d: dict, key: str) -> str | None:
    v = d.get(key)
    return str(v) if v is not None else None


async def _save_process_log(db: AsyncSession, device_id: str, device_name: str, timestamp: int, data: dict):
    log = IotProcessLog(
        device_id=device_id,
        device_name=device_name or "",
        event_time=timestamp,

        blade_id=_str(data, "blade_id"),
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
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def _save_flatness_data(db: AsyncSession, device_id: str, device_name: str, timestamp: int, data: dict):
    rec = IotFlatnessData(
        device_id=device_id,
        device_name=device_name or "",
        event_time=timestamp,

        measure_time=_int(data, "measure_time"),
        blade_id=_str(data, "blade_id"),
        max_value=_float(data, "max_value"),
        min_value=_float(data, "min_value"),
        pv_value=_float(data, "pv_value"),
        rms=_float(data, "rms"),
        hole_angle=data.get("hole_angle"),
        hole_value=data.get("hole_value"),
        process_stage=_str(data, "process_stage"),
    )
    db.add(rec)
    await db.commit()
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
