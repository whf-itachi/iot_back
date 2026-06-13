"""设备表 - 从 JetLinks 同步"""
import datetime
from sqlalchemy import String, Integer, BigInteger, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class IotDevice(Base):
    __tablename__ = "iot_device"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="JetLinks设备ID")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="设备名称")
    description: Mapped[str | None] = mapped_column(String(500), comment="描述")
    product_id: Mapped[str | None] = mapped_column(String(64), comment="所属产品ID")
    product_name: Mapped[str | None] = mapped_column(String(200), comment="产品名称")
    state_text: Mapped[str | None] = mapped_column(String(20), comment="状态文本")
    state_value: Mapped[str | None] = mapped_column(String(20), comment="状态值")
    device_type_text: Mapped[str | None] = mapped_column(String(50), comment="设备类型名称")
    device_type_value: Mapped[str | None] = mapped_column(String(50), comment="设备类型值")
    photo_url: Mapped[str | None] = mapped_column(String(500), comment="设备图片URL")
    registry_time: Mapped[int | None] = mapped_column(BigInteger, comment="注册时间戳")
    create_time_jetlinks: Mapped[int | None] = mapped_column(BigInteger, comment="JetLinks创建时间戳")
    creator_id: Mapped[str | None] = mapped_column(String(64), comment="创建者ID")
    creator_name: Mapped[str | None] = mapped_column(String(100), comment="创建者名称")
    tenant_id: Mapped[int | None] = mapped_column(Integer, default=0, comment="归属租户ID")
    sync_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, server_default=func.now(), comment="最后同步时间"
    )
