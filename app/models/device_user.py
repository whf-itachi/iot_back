"""设备-用户绑定表"""
import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class IotDeviceUser(Base):
    __tablename__ = "iot_device_user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="主键")
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="设备ID")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="用户ID")
    create_time: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="绑定时间"
    )
