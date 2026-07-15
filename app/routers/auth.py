"""认证路由 — /api/sys/login, /api/sys/user/changePassword, /api/sys/token/refresh"""
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import auth_service, operation_log_service
from ..utils.security import get_current_user, decode_token, create_access_token
from ..utils.ip import get_client_ip
from ..models.user import SysUser

router = APIRouter(tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePwdRequest(BaseModel):
    username: str = ""  # 未登录时（密码过期）需提供；已登录时可选，优先从 Token 取
    password: str        # 原密码
    newpassword: str     # 新密码


@router.post("/sys/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = await auth_service.login(db, req.username, req.password)
        return Result.ok(data, "登录成功")
    except ValueError as e:
        msg = str(e)
        if msg.startswith("PWD_EXPIRED:"):
            return Result(code=4001, success=False, message=msg.replace("PWD_EXPIRED:", "", 1), result=None)
        return Result.error(msg)


@router.post("/sys/token/refresh")
async def refresh_access_token(
    db: AsyncSession = Depends(get_db),
    x_refresh_token: str = Header(..., alias="X-Refresh-Token"),
):
    """用 Refresh Token 换取新的 Access Token"""
    try:
        payload = decode_token(x_refresh_token)
    except Exception:
        return Result(code=401, success=False, message="Refresh Token 无效或已过期", result=None)

    if payload.get("type") != "refresh":
        return Result(code=401, success=False, message="请使用 Refresh Token", result=None)

    user_id = payload.get("sub")
    if not user_id:
        return Result(code=401, success=False, message="Token 缺少用户标识", result=None)

    # 查库确认用户仍有效
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.status != 1:
        return Result(code=401, success=False, message="用户不存在或已被禁用", result=None)

    new_token = create_access_token(user.id, user.username, user.role_type or "employee")
    return Result.ok({
        "token": new_token,
        "userInfo": {
            "id": user.id, "username": user.username,
            "realname": user.realname, "role": user.role_type,
        },
    }, "Token 已刷新")


@router.put("/sys/user/changePassword")
async def change_password(
    req: ChangePwdRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """修改密码。已登录用户从 Token 取身份；未登录用户（密码过期）需提供用户名+原密码"""
    # 优先从 Token 取用户名，无 Token 时从请求体取
    username = current_user.get("username") or req.username
    if not username:
        return Result.error("缺少用户名")
    try:
        await auth_service.change_password(db, username, req.password, req.newpassword)
        # 记录操作日志
        await operation_log_service.create_log(
            db, account=username, operation_type="用户修改密码",
            detail=f"用户 {username} 修改了密码",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "密码修改成功")
    except ValueError as e:
        return Result.error(str(e))
