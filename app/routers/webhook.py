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


@router.post("/webhook/event")
async def receive_event(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_webhook_token),
):
    """接收 JetLinks Webhook 推送事件（宽松解析，适配 JetLinks 原生格式）"""

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8") if raw_body else ""

    # 记录原始数据，方便调试 JetLinks 推送格式
    logger.info(f"收到 Webhook 推送:\n{raw_text[:2000]}")

    # 解析原始 JSON
    try:
        body = json.loads(raw_text) if raw_text else {}
    except json.JSONDecodeError:
        # 纯文本体也记日志
        webhook_service.save_webhook_log(db, "", "", "unknown", 0, raw_text)
        await db.commit()
        return Result.ok(None, "已记录原始数据到推送日志")

    if not isinstance(body, dict):
        webhook_service.save_webhook_log(db, "", "", "unknown", 0, raw_text)
        await db.commit()
        return Result.ok(None, "已记录原始数据到推送日志")

    # 从 body 中提取关键字段（兼容 JetLinks 多种命名风格）
    device_id = (
        body.get("deviceId")
        or body.get("device_id")
        or body.get("deviceID")
        or ""
    )
    device_name = (
        body.get("deviceName")
        or body.get("device_name")
        or ""
    )
    event_type = (
        body.get("event")
        or body.get("eventType")
        or body.get("event_type")
        or ""
    )
    timestamp = (
        body.get("timestamp")
        or body.get("eventTime")
        or body.get("event_time")
        or 0
    )
    # 事件数据可能在 data / payload / properties 字段中
    event_data = (
        body.get("data")
        or body.get("payload")
        or body.get("properties")
        or body
    )
    if isinstance(event_data, dict):
        event_data = {**event_data}  # 浅拷贝

    try:
        result = await webhook_service.save_event(
            db=db,
            device_id=str(device_id),
            device_name=str(device_name),
            event_type=str(event_type),
            timestamp=int(timestamp) if timestamp else 0,
            data=event_data if isinstance(event_data, dict) else {},
            raw_body=raw_text,
        )
        if result is None:
            return Result.ok(None, f"事件已记录到推送日志（event={event_type or '未识别'}）")
        return Result.ok({"id": result.id}, f"事件 {event_type} 已接收")
    except ValueError as e:
        return Result.error(str(e))
    except Exception as e:
        return Result.error(str(e))
