"""JWT 和密码工具"""
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..database import get_db


class CompositeBearer:
    """同时支持 Authorization: Bearer 和 X-Access-Token 两种 Token 传递方式"""

    def __init__(self, auto_error: bool = False):
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        token: str | None = None
        # 1. 标准 Authorization: Bearer <token>
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ")
        # 2. 自定义 X-Access-Token（前端用）
        if not token:
            token = request.headers.get("X-Access-Token")
        # 3. Refresh Token
        if not token:
            token = request.headers.get("X-Refresh-Token")

        if not token:
            if self.auto_error:
                raise HTTPException(status_code=401, detail="请提供认证 Token")
            return None

        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


security = CompositeBearer(auto_error=False)


# ==================== 密码 ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def is_password_expired(pwd_update_time: datetime | None) -> bool:
    """判断密码是否已过期"""
    if settings.password_expire_days <= 0:
        return False
    if pwd_update_time is None:
        return False
    if pwd_update_time.tzinfo is None:
        pwd_update_time = pwd_update_time.replace(tzinfo=timezone.utc)
    expire_time = pwd_update_time + timedelta(days=settings.password_expire_days)
    return datetime.now(timezone.utc) > expire_time


# ==================== Access Token + Refresh Token ====================

def create_access_token(user_id: str, username: str, role: str) -> str:
    """签发短期 Access Token（用于 API 请求鉴权）"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    """签发长期 Refresh Token（仅用于换取新 Access Token）"""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码任意 Token，过期或无效统一抛 401"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token无效或已过期")


# ==================== 依赖注入 ====================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """可选认证 — 某些端点不需要强制登录"""
    if credentials is None:
        return {}
    return decode_token(credentials.credentials)


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """强制要求登录，无 Token 直接 401"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    payload = decode_token(credentials.credentials)
    # 仅拒绝明确标记为非 access 的 Token（如 refresh token）
    token_type = payload.get("type")
    if token_type and token_type != "access":
        raise HTTPException(status_code=401, detail="请使用 Access Token")
    return payload


async def require_admin(
    current_user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """要求管理员及以上角色。优先从 JWT 读角色（零查询），旧 Token 回退查库"""
    from ..models.user import SysUser
    role = current_user.get("role", "")
    if not role:
        # 兼容旧 Token（无 role 字段），查库兜底
        result = await db.execute(
            select(SysUser.role_type).where(SysUser.id == current_user.get("sub"))
        )
        role = result.scalar_one_or_none() or ""
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    return current_user


async def check_in_my_chain(db: AsyncSession, operator: dict, target_user_id: str) -> None:
    """权限检查：superadmin 可操作任何人；其他人只能操作自己名下（沿 parent_id 链向上查找）"""
    from ..models.user import SysUser
    role = operator.get("role", "")
    if role == "superadmin":
        return
    operator_id = operator.get("sub", "")
    if not operator_id:
        raise HTTPException(status_code=403, detail="无法识别操作者身份")
    if operator_id == target_user_id:
        return
    current_id = target_user_id
    visited = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        r = await db.execute(select(SysUser.parent_id).where(SysUser.id == current_id))
        row = r.first()
        parent = row[0] if row else None
        if parent == operator_id:
            return
        current_id = parent
    raise HTTPException(status_code=403, detail="该用户不在您名下，无权操作")
