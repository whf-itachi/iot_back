"""Webhook 路由 — 接收 JetLinks 平台推送的事件数据"""
import json
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..config import settings
from ..schemas.response import Result
from ..services import webhook_service
from ..services.device_service import get_my_device_ids
from ..utils.logger import logger
from ..utils.security import require_auth

router = APIRouter(tags=["Webhook"])


async def verify_webhook_token(
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> str:
    """验证 Webhook 鉴权 Token"""
    expected = settings.webhook_token
    if not expected:
        return ""
    if x_webhook_token == expected:
        return x_webhook_token
    raise HTTPException(status_code=401, detail="Webhook Token 无效")


@router.post("/webhook/event/process_log")
async def receive_process_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_webhook_token),
):
    """接收叶片加工日志（JetLinks 推送 process_log_report）"""

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8") if raw_body else ""
    logger.info(f"收到加工日志推送:\n{raw_text[:2000]}")

    body = _parse_body(raw_text)
    if body is None:
        webhook_service.save_webhook_log(db, "", "", "process_log_report", 0, raw_text)
        await db.commit()
        return Result.ok(None, "已记录原始数据到推送日志")

    device_id = str(body.get("deviceId") or body.get("sourceId") or "")
    device_name = str(body.get("deviceName") or body.get("sourceName") or "")
    # timestamp 优先取顶层，没有则从 scene 中取
    timestamp = int(body.get("timestamp") or 0)
    if not timestamp:
        scene = body.get("scene")
        if isinstance(scene, dict):
            timestamp = int(scene.get("timestamp") or 0)
    event_data = body.get("data") if isinstance(body.get("data"), dict) else {}

    client_ip = request.client.host if request.client else "0.0.0.0"

    try:
        event = await webhook_service.save_event(
            db=db, device_id=device_id, device_name=device_name,
            event_type="process_log_report", timestamp=timestamp,
            data=event_data, raw_body=raw_text, client_ip=client_ip,
        )
        logger.info(f"加工日志写入成功: id={event.id}, device={device_name}")
        return Result.ok({"id": event.id}, "加工日志已接收")
    except Exception as e:
        logger.error(f"加工日志写入失败 device={device_name}: {e}", exc_info=True)
        return Result.error(str(e))


@router.post("/webhook/event/flatness_data")
async def receive_flatness_data(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_webhook_token),
):
    """接收平面度测量数据（JetLinks 推送 flatness_data）"""

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8") if raw_body else ""
    logger.info(f"收到平面度推送:\n{raw_text[:2000]}")

    body = _parse_body(raw_text)
    if body is None:
        webhook_service.save_webhook_log(db, "", "", "flatness_data", 0, raw_text)
        await db.commit()
        return Result.ok(None, "已记录原始数据到推送日志")

    device_id = str(body.get("deviceId") or body.get("sourceId") or "")
    device_name = str(body.get("deviceName") or body.get("sourceName") or "")
    # timestamp 优先取顶层，没有则从 scene 中取
    timestamp = int(body.get("timestamp") or 0)
    if not timestamp:
        scene = body.get("scene")
        if isinstance(scene, dict):
            timestamp = int(scene.get("timestamp") or 0)
    event_data = body.get("data") if isinstance(body.get("data"), dict) else {}

    client_ip = request.client.host if request.client else "0.0.0.0"

    try:
        event = await webhook_service.save_event(
            db=db, device_id=device_id, device_name=device_name,
            event_type="flatness_data", timestamp=timestamp,
            data=event_data, raw_body=raw_text, client_ip=client_ip,
        )
        logger.info(f"平面度数据写入成功: id={event.id}, blade_id={event_data.get('blade_id', '')}, device={device_name}")
        return Result.ok({"id": event.id}, "平面度数据已接收")
    except Exception as e:
        logger.error(f"平面度数据写入失败 device={device_name}: {e}", exc_info=True)
        return Result.error(str(e))


@router.post("/webhook/event/alarm")
async def receive_alarm(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_webhook_token),
):
    """接收设备告警上报（JetLinks 推送 alarm_report 事件）

    JetLinks 配置 webhook 订阅，将告警事件推送到本接口，并携带 X-Webhook-Token 头
    （值与 .env 的 WEBHOOK_TOKEN 一致；开发环境留空则不校验）。
    推送到达即解析设备ID / 报警内容 / 报警时间，写入 iot_alarm 表。
    """

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8") if raw_body else ""
    logger.info(f"收到告警推送:\n{raw_text[:2000]}")

    # 优先按 JSON 解析；非 JSON 时兼容「key:value」纯文本（与设备状态同款格式）
    body = _parse_body(raw_text)
    if body is None:
        body = _parse_kv_text(raw_text)
    if body is None:
        webhook_service.save_webhook_log(db, "", "", "alarm_report", 0, raw_text)
        await db.commit()
        return Result.ok(None, "已记录原始数据到推送日志")

    # 告警解析与存储由独立的 save_alarm 处理（不共用 save_event，字段显式、无 device_name）
    try:
        event = await webhook_service.save_alarm(db=db, body=body, raw_body=raw_text)
        if event is None:
            return Result.ok(None, "告警数据无效，已跳过（缺少设备ID或报警内容）")
        logger.info(f"告警写入成功: id={event.id}, device={event.device_id}")
        return Result.ok({"id": event.id}, "告警已接收")
    except Exception as e:
        logger.error(f"告警写入失败: {e}", exc_info=True)
        return Result.error(str(e))


def _parse_body(raw_text: str) -> dict | None:
    """解析 webhook 请求体（标准 JSON）。非 JSON 返回 None。

    加工日志 / 平面度数据推送均为 JSON；设备状态推送走专用 _parse_device_state。
    """
    try:
        obj = json.loads(raw_text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_device_state(raw_text: str) -> tuple[str | None, bool | None]:
    """解析设备状态推送（固定格式：key: value 多行纯文本）。

        deviceId: 156461687
        online: True

    返回 (device_id, is_online)。deviceId 缺失返回 (None, None)，online 缺失返回 (device_id, None)。
    """
    device_id = None
    is_online = None
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key in ("deviceid", "device_id"):
            device_id = val
        elif key == "online":
            is_online = val.lower() in ("true", "1", "online", "on", "yes")
    return device_id, is_online


def _parse_kv_text(raw_text: str) -> dict | None:
    """解析「key: value」多行纯文本为 dict（键统一转小写）。

    用于兼容非 JSON 的告警推送（如与设备状态同款的纯文本格式）。
    无有效键值对时返回 None。
    """
    out: dict[str, str] = {}
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip().lower()] = val.strip()
    return out or None


@router.post("/webhook/event/device_state")
async def receive_device_state(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_webhook_token),
):
    """接收设备上下线状态变更（JetLinks 推送 device_online / device_offline 事件）

    JetLinks 需配置一个 webhook 订阅，将上述事件推送到本接口，
    并携带 X-Webhook-Token 头（值与 .env 的 WEBHOOK_TOKEN 一致）。
    推送到达即更新本地 iot_device 状态，使首页在线设备数保持实时。
    """

    # ================= 调试日志：打印接收到的全部数据 =================
    client_ip = request.client.host if request.client else "0.0.0.0"
    logger.info(
        "【设备状态推送】接收到请求 → "
        f"client_ip={client_ip}, "
        f"content_type={request.headers.get('content-type')}, "
        f"has_webhook_token={'X-Webhook-Token' in request.headers}"
    )

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8") if raw_body else ""
    logger.info(f"【设备状态推送】原始请求体(raw_body):\n{raw_text}")

    device_id, is_online = _parse_device_state(raw_text)
    state_value = "online" if is_online else "offline"
    state_text = "在线" if is_online else "离线"
    logger.info(
        "【设备状态推送】解析结果 → device_id=%s, state_value=%s, state_text=%s",
        device_id, state_value, state_text,
    )

    if not device_id or is_online is None:
        logger.warning(f"【设备状态推送】字段缺失: device_id={device_id}, is_online={is_online}")
        webhook_service.save_webhook_log(db, device_id or "", "", "device_state", 0, raw_text)
        await db.commit()
        return Result.ok(None, "设备ID或在线状态缺失，已记录原始数据")

    try:
        await webhook_service.upsert_device_state(
            db=db, device_id=device_id, device_name="",
            state_value=state_value, state_text=state_text,
            timestamp=0, raw_text=raw_text,
        )
        logger.info(f"设备状态更新成功: device={device_id} state={state_value}")
        return Result.ok({"deviceId": device_id, "state": state_value}, "设备状态已更新")
    except Exception as e:
        logger.error(f"设备状态更新失败 device={device_id}: {e}", exc_info=True)
        return Result.error(str(e))


@router.get("/webhook/event/alarms")
async def list_alarms(
    device_id: str | None = None,
    start_time: int | None = Query(default=None, description="报警时间范围起点(毫秒时间戳，闭区间)"),
    end_time: int | None = Query(default=None, description="报警时间范围终点(毫秒时间戳，闭区间)"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回条数上限"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """查询已存储的告警记录（按报警时间倒序，支持按设备 + 时间范围过滤；仅返回当前用户所属设备的告警"""
    try:
        allowed = set(await get_my_device_ids(db, current_user.get("username", "")))
        rows = await webhook_service.query_alarms(
            db, device_id=device_id, start_time=start_time, end_time=end_time, limit=limit,
            allowed_ids=allowed,
        )
        return Result.ok(rows, "查询成功")
    except Exception as e:
        logger.error(f"查询告警失败: {e}", exc_info=True)
        return Result.error(str(e))
