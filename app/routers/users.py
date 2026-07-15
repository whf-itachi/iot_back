"""用户管理路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import user_service, operation_log_service
from ..models.user import SysUser
from ..utils.security import require_auth, require_admin
from ..utils.ip import get_client_ip

router = APIRouter(tags=["用户管理"])


class AddUserRequest(BaseModel):
    username: str
    password: str = "123456"
    realname: str = ""

class EditUserRequest(BaseModel):
    realname: str | None = None
    password: str | None = None


class AdminResetPasswordRequest(BaseModel):
    userId: str
    newPassword: str


def _user_label(user) -> str:
    """生成用户可读标识：zhangsan（张三）[abc123]"""
    if not user:
        return "未知用户"
    return f"{user.username}（{user.realname or '未填姓名'}）[{user.id}]"


@router.get("/sys/user/list")
async def list_users(
    pageNo: int = Query(1, alias="pageNo"),
    pageSize: int = Query(200, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_auth),
):
    try:
        data = await user_service.get_user_list(db, pageNo, pageSize)
        return Result.ok(data, "查询成功")
    except Exception as e:
        return Result.error(str(e))


@router.post("/sys/user/add")
async def add_user(
    req: AddUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        data = await user_service.add_user(db, req.model_dump())
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="新增用户",
            detail=f"新增用户 {req.username}（{req.realname or '未填姓名'}）",
            ip_address=get_client_ip(request),
        )
        return Result.ok(data, "新增成功")
    except ValueError as e:
        return Result.error(str(e))


@router.put("/sys/user/edit")
async def edit_user(
    req: EditUserRequest,
    request: Request,
    id: str = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        # 先查用户信息用于日志
        result = await db.execute(select(SysUser).where(SysUser.id == id))
        user = result.scalar_one_or_none()
        label = _user_label(user)

        changes = []
        if req.realname is not None:
            changes.append(f"姓名改为「{req.realname}」")
        if req.password is not None:
            changes.append("修改了密码")

        await user_service.edit_user(db, id, req.model_dump(exclude_none=True))
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="编辑用户",
            detail=f"编辑用户 {label}：" + ("，".join(changes) if changes else "无实际变更"),
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "修改成功")
    except ValueError as e:
        return Result.error(str(e))


@router.delete("/sys/user/delete")
async def delete_user(
    request: Request,
    id: str = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        # 先查用户信息（删之前拿到标识），再执行删除
        result = await db.execute(select(SysUser).where(SysUser.id == id))
        user = result.scalar_one_or_none()
        label = _user_label(user)
        await user_service.delete_user(db, id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="删除用户",
            detail=f"删除用户 {label}",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "删除成功")
    except ValueError as e:
        return Result.error(str(e))


@router.put("/sys/user/adminResetPassword")
async def admin_reset_password(
    req: AdminResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """管理员重置任意用户密码（无需旧密码）"""
    try:
        # 先查用户信息用于日志
        result = await db.execute(select(SysUser).where(SysUser.id == req.userId))
        user = result.scalar_one_or_none()
        label = _user_label(user)
        await user_service.reset_user_password(db, req.userId, req.newPassword)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="管理员重置密码",
            detail=f"管理员 {_admin.get('username', '')} 重置了用户 {label} 的密码",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "密码重置成功")
    except ValueError as e:
        return Result.error(str(e))
