"""操作日志表 — 记录所有数据修改操作"""
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class SysOperationLog(Base):
    __tablename__ = "sys_operation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="日志ID")
    operate_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="操作时间"
    )
    account: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment="操作账号")
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="操作类型")
    detail: Mapped[str] = mapped_column(Text, nullable=False, comment="操作详情描述")
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="请求IP地址")
