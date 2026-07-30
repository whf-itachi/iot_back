"""Webhook 事件处理服务 — 按事件类型写入对应表"""
import asyncio
import json
import re
from datetime import datetime
from sqlalchemy import select, desc, and_, or_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.iot_event import IotWebhookLog, IotProcessLog, IotFlatnessData
from ..models.operation_log import SysOperationLog
from ..utils.logger import logger

# 审计日志中统一使用的操作账号（超管）
AUDIT_ACCOUNT = "admin"


async def save_event(
    db: AsyncSession,
    device_id: str,
    device_name: str,
    event_type: str,
    timestamp: int,
    data: dict,
    raw_body: str = "",
    client_ip: str = "0.0.0.0",
):
    """根据事件类型保存到对应的表中，同时记录推送日志。

    对 MySQL 连接丢失等瞬时错误自动重试（最多 3 次，指数退避），
    重试时会重新创建整个事务（webhook 日志 + 业务数据 + 操作日志）。
    """
    blade_id = data.get("blade_id", "")
    logger.info(f"[save_event] 开始处理 event_type={event_type}, device_id={device_id}, blade_id={blade_id}, client_ip={client_ip}")

    max_retries = 3
    base_delay = 0.5  # 基础等待秒数

    for attempt in range(max_retries):
        # 每次尝试都重新添加 webhook 日志（因为 rollback 后会清除）
        save_webhook_log(db, device_id, device_name, event_type, timestamp, raw_body)
        logger.debug(f"[save_event] webhook 推送日志已加入会话 (attempt {attempt+1}/{max_retries})")

        try:
            if event_type == "process_log_report":
                result = await _save_process_log(db, device_id, device_name, timestamp, data, client_ip=client_ip)
            elif event_type == "flatness_data":
                result = await _save_flatness_data(db, device_id, device_name, timestamp, data, client_ip=client_ip)
            else:
                # 未知类型只记日志，不写入业务表
                logger.warning(f"[save_event] 未知事件类型: {event_type}，仅记录推送日志")
                await db.commit()
                return None

            if result is None:
                # 数据被守卫逻辑跳过（device_id / blade_id 为空），不视为失败
                logger.warning(f"[save_event] 数据无效被跳过 event_type={event_type}, device_id={device_id}")
                return None

            logger.info(f"[save_event] 写入成功 event_type={event_type}, id={result.id}")
            return result

        except OperationalError as e:
            await db.rollback()
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # 0.5s → 1.0s → 2.0s
                logger.warning(
                    f"[save_event] 写入失败 (attempt {attempt+1}/{max_retries}), "
                    f"event_type={event_type}, blade_id={blade_id}: "
                    f"{e._message() if hasattr(e, '_message') else e}"
                    f" — {delay}s 后重试..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"[save_event] 写入数据库失败（已重试 {max_retries} 次） "
                             f"event_type={event_type}, device_id={device_id}: {e}", exc_info=True)
                raise

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

# 匹配日期时间字符串："2026-05-13 00:18:07" / "2026-05-13T00:18:07" / "2026-05-13 09:44"（无秒）
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")


def _parse_datetime_to_ms(v: str) -> int:
    """将多种日期时间字符串转为毫秒时间戳，失败返回 0。

    支持格式：
      - "2026-05-13 00:18:07" / "2026-05-13T00:18:07"（精确到秒）
      - "2026-05-13 09:44" / "2026-05-13T09:44"       （精确到分钟）
    """
    try:
        v = v.replace("T", " ").strip()
        # 根据长度选择合适的格式
        if len(v) >= 19:
            dt = datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")
        elif len(v) >= 16:
            dt = datetime.strptime(v[:16], "%Y-%m-%d %H:%M")
        else:
            return 0
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


async def _save_process_log(db: AsyncSession, device_id: str, device_name: str, timestamp: int, data: dict, client_ip: str = "0.0.0.0"):
    blade_id = _str(data, "blade_id")

    # 守卫：设备ID / 叶片ID 必须有值才写入，缺失则跳过（不写 NULL）
    if not device_id or not blade_id:
        logger.warning(f"[_save_process_log] 跳过：device_id 或 blade_id 为空 (device={device_id}, blade={blade_id})")
        return None

    logger.info(f"[_save_process_log] 准备写入: blade_id={blade_id}, device={device_name}")

    # 写入前判断 新增 / 修改（用于审计日志），并保留修改前的快照
    old = await db.scalar(
        select(IotProcessLog).where(
            IotProcessLog.device_id == device_id,
            IotProcessLog.blade_id == blade_id,
        )
    )
    exists = old is not None
    old_dict = _process_log_to_dict(old) if old else None

    values = dict(
        blade_id=blade_id,
        device_id=device_id,
        device_name=device_name or "",
        event_time=timestamp,
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

    stmt = mysql_insert(IotProcessLog).values(**values)
    # (device_id, blade_id) 命中唯一约束时，更新其他字段
    stmt = stmt.on_duplicate_key_update(
        device_id=stmt.inserted.device_id,
        device_name=stmt.inserted.device_name,
        event_time=stmt.inserted.event_time,
        operator=stmt.inserted.operator,
        process_start_time=stmt.inserted.process_start_time,
        process_end_time=stmt.inserted.process_end_time,
        total_duration=stmt.inserted.total_duration,
        factory=stmt.inserted.factory,
        device_type_code=stmt.inserted.device_type_code,
        scan_result=stmt.inserted.scan_result,
        bolt_sleeve_max=stmt.inserted.bolt_sleeve_max,
        bolt_sleeve_min=stmt.inserted.bolt_sleeve_min,
        pitch_angle=stmt.inserted.pitch_angle,
        yaw_angle=stmt.inserted.yaw_angle,
        bcd_estimate=stmt.inserted.bcd_estimate,
        before_flatness=stmt.inserted.before_flatness,
        mill_depth=stmt.inserted.mill_depth,
        mill_cycles=stmt.inserted.mill_cycles,
        mill_result=stmt.inserted.mill_result,
        after_flatness=stmt.inserted.after_flatness,
        adjust_leg_time=stmt.inserted.adjust_leg_time,
        laser_adjust_time=stmt.inserted.laser_adjust_time,
        rough_scan_time=stmt.inserted.rough_scan_time,
        fine_scan_time=stmt.inserted.fine_scan_time,
        mill_time=stmt.inserted.mill_time,
        scan_report_time=stmt.inserted.scan_report_time,
        upper_avg_power=stmt.inserted.upper_avg_power,
        upper_max_power=stmt.inserted.upper_max_power,
        lower_avg_power=stmt.inserted.lower_avg_power,
        lower_max_power=stmt.inserted.lower_max_power,
    )

    logger.debug(f"[_save_process_log] 执行 upsert")
    await db.execute(stmt)

    # 操作审计日志：与业务数据同事务提交，确保原子性
    operation_type = "修改叶片加工日志" if exists else "新增叶片加工日志"
    detail = _build_op_detail("修改" if exists else "新增", "叶片加工日志", device_id, blade_id, values, old_dict)
    db.add(SysOperationLog(
        account=AUDIT_ACCOUNT,
        operation_type=operation_type,
        detail=detail,
        ip_address=client_ip,
    ))

    await db.commit()

    # 查询回记录以获取 id
    log = await db.scalar(
        select(IotProcessLog).where(
            IotProcessLog.device_id == device_id,
            IotProcessLog.blade_id == blade_id,
        )
    )
    logger.info(f"[_save_process_log] upsert 成功: id={log.id}, blade_id={blade_id}, op={operation_type}")
    await db.refresh(log)
    return log


async def _save_flatness_data(db: AsyncSession, device_id: str, device_name: str, timestamp: int, data: dict, client_ip: str = "0.0.0.0"):
    blade_id = _str(data, "blade_id")

    # 守卫：设备ID / 叶片ID 必须有值才写入，缺失则跳过（不写 NULL）
    if not device_id or not blade_id:
        logger.warning(f"[_save_flatness_data] 跳过：device_id 或 blade_id 为空 (device={device_id}, blade={blade_id})")
        return None

    process_stage = _str(data, "process_stage") or "before"
    measure_time = _int(data, "measure_time")
    logger.info(f"[_save_flatness_data] 准备写入: blade_id={blade_id}, stage={process_stage}, device={device_name}")

    # 写入前判断 新增 / 修改（用于审计日志），并保留修改前的快照
    old = await db.scalar(
        select(IotFlatnessData).where(
            IotFlatnessData.device_id == device_id,
            IotFlatnessData.blade_id == blade_id,
            IotFlatnessData.process_stage == process_stage,
        )
    )
    exists = old is not None
    old_dict = _flatness_to_dict(old) if old else None

    values = dict(
        blade_id=blade_id,
        process_stage=process_stage,
        device_id=device_id,
        device_name=device_name or "",
        event_time=timestamp,
        measure_time=measure_time,
        max_value=_float(data, "max_value"),
        min_value=_float(data, "min_value"),
        pv_value=_float(data, "pv_value"),
        rms=_float(data, "rms"),
        hole_angle=data.get("hole_angle"),
        hole_value=data.get("hole_value"),
    )

    stmt = mysql_insert(IotFlatnessData).values(**values)
    # (device_id, blade_id, process_stage) 命中唯一约束时，更新其他字段
    stmt = stmt.on_duplicate_key_update(
        device_id=stmt.inserted.device_id,
        device_name=stmt.inserted.device_name,
        event_time=stmt.inserted.event_time,
        measure_time=stmt.inserted.measure_time,
        max_value=stmt.inserted.max_value,
        min_value=stmt.inserted.min_value,
        pv_value=stmt.inserted.pv_value,
        rms=stmt.inserted.rms,
        hole_angle=stmt.inserted.hole_angle,
        hole_value=stmt.inserted.hole_value,
    )

    logger.debug(f"[_save_flatness_data] 执行 upsert")
    await db.execute(stmt)

    # 操作审计日志：与业务数据同事务提交，确保原子性
    operation_type = "修改平面度测量数据" if exists else "新增平面度测量数据"
    detail = _build_op_detail("修改" if exists else "新增", "平面度测量数据", device_id, blade_id, values, old_dict)
    db.add(SysOperationLog(
        account=AUDIT_ACCOUNT,
        operation_type=operation_type,
        detail=detail,
        ip_address=client_ip,
    ))

    await db.commit()

    # 查询回记录以获取 id
    rec = await db.scalar(
        select(IotFlatnessData).where(
            IotFlatnessData.device_id == device_id,
            IotFlatnessData.blade_id == blade_id,
            IotFlatnessData.process_stage == process_stage,
        )
    )
    logger.info(f"[_save_flatness_data] upsert 成功: id={rec.id}, blade_id={blade_id}, stage={process_stage}, op={operation_type}")
    await db.refresh(rec)
    return rec


def _build_op_detail(op_label: str, entity_label: str, device_id: str, blade_id: str, values: dict, old_dict: dict | None) -> str:
    """构造操作日志 detail：记录写入/修改的完整数据；修改时附带修改前快照。"""
    parts = [
        f"{op_label}{entity_label}",
        f"设备ID: {device_id}",
        f"叶片ID: {blade_id}",
    ]
    if old_dict is not None:
        parts.append("修改前: " + json.dumps(old_dict, ensure_ascii=False, default=str))
    parts.append(("修改后: " if old_dict is not None else "数据: ") + json.dumps(values, ensure_ascii=False, default=str))
    return "\n".join(parts)


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


def _base_dict(r) -> dict:
    """Common fields present in both process log and flatness dicts."""
    return {
        "_deviceId": r.device_id,
        "_deviceName": r.device_name,
        "_timestamp": r.event_time,
        "_logId": str(r.id),
        "device_id": r.device_id,
        "device_name": r.device_name,
        "event_time": r.event_time,
        "blade_id": r.blade_id,
    }


def _process_log_to_dict(r: IotProcessLog) -> dict:
    return {
        **_base_dict(r),
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

    # 按 blade_id 分组，提取 before/after；rows 已按时间倒序，首次出现即最新
    blade_map: dict[str, dict] = {}
    for r in rows:
        bid = r.blade_id or f"unknown_{r.id}"
        if bid not in blade_map:
            blade_map[bid] = {
                "blade_id": bid,
                "device_name": r.device_name,
                "_deviceId": r.device_id,
                "_sort_time": r.event_time or 0,
                "measure_time": r.measure_time,
            }
        stage = r.process_stage or "before"
        if stage not in blade_map[bid]:
            blade_map[bid][stage] = _flatness_to_dict(r)
        # 如果首条记录的 measure_time 为空，用后续记录的补上
        if not blade_map[bid].get("measure_time") and r.measure_time:
            blade_map[bid]["measure_time"] = r.measure_time

    # 按时间倒序，最新数据在最上面
    return sorted(blade_map.values(), key=lambda x: x.get("_sort_time", 0) or 0, reverse=True)[:limit]


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
            "_deviceId": r.device_id,
            "operator": r.operator,
            "mill_result": r.mill_result,
            "process_start_time": r.process_start_time,
            "log": _process_log_to_dict(r),
        })
    return blades


def _flatness_to_dict(r: IotFlatnessData) -> dict:
    return {
        **_base_dict(r),
        "measure_time": r.measure_time,
        "max_value": r.max_value,
        "min_value": r.min_value,
        "pv_value": r.pv_value,
        "rms": r.rms,
        "hole_angle": r.hole_angle,
        "hole_value": r.hole_value,
        "process_stage": r.process_stage,
    }


async def query_flatness_exact(
    db: AsyncSession,
    blade_id: str,
    process_stage: str | None = None,
) -> list[IotFlatnessData]:
    """Exact-match query for single blade flatness by blade_id + optional stage."""
    stmt = select(IotFlatnessData).where(IotFlatnessData.blade_id == blade_id)
    if process_stage:
        stmt = stmt.where(IotFlatnessData.process_stage == process_stage)
    stmt = stmt.order_by(desc(IotFlatnessData.event_time), desc(IotFlatnessData.id)).limit(2)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def query_process_logs_exact(
    db: AsyncSession,
    blade_id: str,
) -> list[IotProcessLog]:
    """Exact-match query for single blade process log by blade_id."""
    stmt = (
        select(IotProcessLog)
        .where(IotProcessLog.blade_id == blade_id)
        .order_by(desc(IotProcessLog.event_time), desc(IotProcessLog.id))
        .limit(1)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def query_process_logs_for_download(
    db: AsyncSession,
    device_names: list[str] | None = None,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[IotProcessLog]:
    """查询加工日志用于批量下载，支持按设备名列表和时间范围过滤。

    时间过滤使用 event_time（始终为毫秒时间戳），若 event_time 为空则包含该记录。
    """

    stmt = (
        select(IotProcessLog)
        .order_by(desc(IotProcessLog.event_time), desc(IotProcessLog.id))
    )

    conditions = []
    if device_names:
        conditions.append(IotProcessLog.device_name.in_(device_names))
    if start_time_ms is not None:
        conditions.append(
            or_(IotProcessLog.event_time >= start_time_ms,
                IotProcessLog.event_time.is_(None))
        )
    if end_time_ms is not None:
        conditions.append(
            or_(IotProcessLog.event_time <= end_time_ms,
                IotProcessLog.event_time.is_(None))
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def query_flatness_for_download(
    db: AsyncSession,
    device_names: list[str] | None = None,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[IotFlatnessData]:
    """查询平面度数据用于批量下载，支持按设备名列表和时间范围过滤。

    时间过滤使用 event_time（始终为毫秒时间戳），若 event_time 为空则包含该记录。
    """

    stmt = (
        select(IotFlatnessData)
        .order_by(desc(IotFlatnessData.event_time), desc(IotFlatnessData.id))
    )

    conditions = []
    if device_names:
        conditions.append(IotFlatnessData.device_name.in_(device_names))
    if start_time_ms is not None:
        conditions.append(
            or_(IotFlatnessData.event_time >= start_time_ms,
                IotFlatnessData.event_time.is_(None))
        )
    if end_time_ms is not None:
        conditions.append(
            or_(IotFlatnessData.event_time <= end_time_ms,
                IotFlatnessData.event_time.is_(None))
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def query_flatness_statistics(
    db: AsyncSession,
    device_name: str | None = None,
) -> list[dict]:
    """查询叶片的加工前后平面度对比统计

    从 iot_process_log 中提取每片叶子的 before_flatness / after_flatness，
    计算变化量，按 blade_id 去重取最新一条。
    可通过 device_name（设备名称）进行过滤。
    """

    stmt = (
        select(IotProcessLog)
        .order_by(desc(IotProcessLog.event_time), desc(IotProcessLog.id))
    )
    if device_name:
        stmt = stmt.where(IotProcessLog.device_name == device_name)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    # 按 blade_id 去重，每片叶子只取最新的记录
    seen = {}
    for r in rows:
        bid = r.blade_id or f"unknown_{r.id}"
        if bid not in seen:
            seen[bid] = r

    stats = []
    for bid, r in seen.items():
        before_val = r.before_flatness
        after_val = r.after_flatness
        # 计算改善量：正值表示平面度变好
        improvement = None
        if before_val is not None and after_val is not None:
            improvement = round(before_val - after_val, 4)

        stats.append({
            "blade_id": bid,
            "device_name": r.device_name,
            "_deviceId": r.device_id,
            "before_flatness": before_val,
            "after_flatness": after_val,
            "improvement": improvement,
            "mill_result": r.mill_result,
            "operator": r.operator,
            "process_start_time": r.process_start_time,
            "event_time": r.event_time,
            "mill_depth": r.mill_depth,
            "total_duration": r.total_duration,
        })

    # 按时间倒序，最新数据在最上面
    return sorted(stats, key=lambda x: x.get("event_time") or 0, reverse=True)


async def query_device_names(
    db: AsyncSession,
    allowed_ids: set[str] | None = None,
) -> list[str]:
    """返回去重后的设备名称列表（可选按可访问设备 ID 过滤），用于前端过滤下拉框。"""

    stmt = select(IotProcessLog.device_name).distinct()
    if allowed_ids is not None:
        if not allowed_ids:
            return []
        stmt = stmt.where(IotProcessLog.device_id.in_(allowed_ids))

    result = await db.execute(stmt)
    names = [n for n in result.scalars().all() if n]
    return sorted(names)
