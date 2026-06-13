"""Webhook 请求体模型"""
from typing import Any
from pydantic import BaseModel


class WebhookPayload(BaseModel):
    """JetLinks Webhook 推送数据格式（假定格式，后期可调）"""
    deviceId: str
    deviceName: str = ""
    event: str                              # process_log_report / flatness_data / fault_report / alarm_log / qc_data
    timestamp: int = 0                      # 毫秒时间戳
    data: dict[str, Any] = {}
