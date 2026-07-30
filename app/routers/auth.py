"""认证路由 — /api/sys/login, /api/sys/user/changePassword, /api/sys/token/refresh"""
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import auth_service, operation_log_service
from ..utils.security import get_current_user, decode_token, create_access_token, create_refresh_token
from ..utils.ip import get_client_ip
from ..models.user import SysUser

router = APIRouter(tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePwdRequest(BaseModel):
    username: str = ""       # 未登录时（密码过期）需提供；已登录时可选，优先从 Token 取
    password: str | None = None    # 原密码：仅修改密码时提供
    newpassword: str | None = None # 新密码：仅修改密码时提供
    newusername: str | None = None  # 可选：同时修改账号名（姓名 realname 不允许在此修改）


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
    """修改个人资料：可单独或同时修改密码与账号名。
    已登录用户从 Token 取身份（优先 sub）；未登录用户（密码过期）需提供用户名+原密码。"""
    user_id = current_user.get("sub")
    username = current_user.get("username") or req.username
    if not user_id and not username:
        return Result.error("缺少用户标识")
    try:
        change_result = await auth_service.change_password(
            db,
            user_id=user_id,
            username=username,
            old_password=req.password,
            new_password=req.newpassword,
            new_username=req.newusername or None,
        )
        # 操作日志（根据实际操作内容记录）
        log_account = change_result["new_username"]
        parts = []
        if change_result["password_changed"]:
            parts.append("修改了密码")
        if change_result["username_changed"]:
            parts.append(f"将账号名改为「{change_result['new_username']}」")
        detail = "用户 " + log_account + ("，" + "，".join(parts) if parts else "：无变更")
        # 操作类型：改了密码用“用户修改密码”（日志页带锁标记），仅改账号名用“用户修改资料”
        op_type = "用户修改密码" if change_result["password_changed"] else "用户修改资料"
        await operation_log_service.create_log(
            db, account=log_account, operation_type=op_type,
            detail=detail,
            ip_address=get_client_ip(request),
        )
        # 已登录用户：重新签发 Token 以保持会话一致（账号名变化时用户名同步更新）
        result = None
        if user_id:
            new_token = create_access_token(
                user_id, change_result["new_username"], current_user.get("role", "employee")
            )
            new_refresh = create_refresh_token(user_id)
            result = {
                "token": new_token,
                "refreshToken": new_refresh,
                "userInfo": {
                    "id": user_id,
                    "username": change_result["new_username"],
                    "role": current_user.get("role", "employee"),
                },
            }
        return Result.ok(result, "修改成功")
    except ValueError as e:
        return Result.error(str(e))
