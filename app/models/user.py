"""用户表"""
import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class SysUser(Base):
    __tablename__ = "sys_user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户ID")
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码(bcrypt)")
    realname: Mapped[str | None] = mapped_column(String(100), comment="姓名")
    phone: Mapped[str | None] = mapped_column(String(20), comment="手机号")
    status: Mapped[int] = mapped_column(Integer, default=1, comment="状态 1=正常 0=禁用")
    role_type: Mapped[str] = mapped_column(String(20), default="employee", comment="角色: superadmin/admin/employee")
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="上级用户ID")
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="所属租户ID")
    create_time: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
