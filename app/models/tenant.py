"""租户表"""
import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class SysTenant(Base):
    __tablename__ = "sys_tenant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="租户ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="租户名称")
    status: Mapped[int] = mapped_column(Integer, default=1, comment="状态 1=正常")
    create_time: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
