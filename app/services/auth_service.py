"""认证服务 — 重构版"""
import uuid
import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.user import SysUser
from ..utils.security import hash_password, verify_password, create_access_token, create_refresh_token, is_password_expired


async def login(db: AsyncSession, username: str, password: str) -> dict:
    result = await db.execute(select(SysUser).where(SysUser.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")
    if user.status != 1:
        raise ValueError("用户已被禁用")
    if not verify_password(password, user.password):
        raise ValueError("密码错误")

    # 检查密码是否过期
    pwd_expired = is_password_expired(user.pwd_update_time)
    if pwd_expired:
        raise ValueError("PWD_EXPIRED:密码已过期，请修改密码后重新登录")

    role = user.role_type or "employee"
    access_token = create_access_token(user.id, user.username, role)
    refresh_token = create_refresh_token(user.id)
    return {
        "token": access_token,
        "refreshToken": refresh_token,
        "userInfo": {
            "id": user.id, "username": user.username,
            "realname": user.realname, "role": role,
        },
    }


async def change_password(db: AsyncSession, username: str, old_password: str, new_password: str) -> None:
    result = await db.execute(select(SysUser).where(SysUser.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")
    if not verify_password(old_password, user.password):
        raise ValueError("原密码错误")
    user.password = hash_password(new_password)
    user.pwd_update_time = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    await db.commit()


async def ensure_admin_user(db: AsyncSession) -> str:
    """初始化超管（首次启动时调用）"""
    from ..config import settings
    result = await db.execute(
        select(SysUser).where(SysUser.username == settings.jetlinks_username))
    admin = result.scalar_one_or_none()
    if admin:
        return admin.id

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    uid = str(uuid.uuid4()).replace("-", "")[:32]
    admin = SysUser(
        id=uid, username="admin",
        password=hash_password(settings.jetlinks_password),
        realname="超级管理员", role_type="superadmin",
        pwd_update_time=now,
    )
    db.add(admin)
    await db.commit()
    return uid
