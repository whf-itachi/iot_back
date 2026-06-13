"""Webhook 路由 — 接收 JetLinks 平台推送的事件数据"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..config import settings
from ..schemas.response import Result
from ..schemas.webhook import WebhookPayload
from ..services import webhook_service

router = APIRouter(tags=["Webhook"])


async def verify_webhook_token(
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> str:
    """验证 Webhook 鉴权 Token"""
    expected = settings.webhook_token
    if not expected:
        return ""  # 未配置 Token 则放行
    if x_webhook_token == expected:
        return x_webhook_token
    raise HTTPException(status_code=401, detail="Webhook Token 无效")


@router.post("/webhook/event")
async def receive_event(
    request: Request,
    payload: WebhookPayload,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(verify_webhook_token),
):
    """接收 JetLinks Webhook 推送事件

    支持的 event 类型：
    - process_log_report  叶片加工日志
    - flatness_data       平面度测量数据
    - fault_report        故障上报
    - alarm_log           报警日志
    - qc_data             质量控制数据

    未知类型仅记录到推送日志表，不写入业务表。
    """
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8") if raw_body else ""

    try:
        result = await webhook_service.save_event(
            db=db,
            device_id=payload.deviceId,
            device_name=payload.deviceName,
            event_type=payload.event,
            timestamp=payload.timestamp,
            data=payload.data,
            raw_body=raw_text,
        )
        if result is None:
            return Result.ok(None, f"事件 {payload.event} 已记录到推送日志（未关联业务表）")
        return Result.ok({"id": result.id}, f"事件 {payload.event} 已接收")
    except ValueError as e:
        return Result.error(str(e))
    except Exception as e:
        return Result.error(str(e))
