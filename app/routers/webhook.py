"""Webhook 路由 — 接收 JetLinks 平台推送的事件数据"""
import json
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..config import settings
from ..schemas.response import Result
from ..services import webhook_service
from ..utils.logger import logger

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

    try:
        event = await webhook_service.save_event(
            db=db, device_id=device_id, device_name=device_name,
            event_type="process_log_report", timestamp=timestamp,
            data=event_data, raw_body=raw_text,
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

    try:
        event = await webhook_service.save_event(
            db=db, device_id=device_id, device_name=device_name,
            event_type="flatness_data", timestamp=timestamp,
            data=event_data, raw_body=raw_text,
        )
        logger.info(f"平面度数据写入成功: id={event.id}, blade_id={event_data.get('blade_id', '')}, device={device_name}")
        return Result.ok({"id": event.id}, "平面度数据已接收")
    except Exception as e:
        logger.error(f"平面度数据写入失败 device={device_name}: {e}", exc_info=True)
        return Result.error(str(e))


def _parse_body(raw_text: str) -> dict | None:
    try:
        body = json.loads(raw_text)
        return body if isinstance(body, dict) else None
    except json.JSONDecodeError:
        return None
