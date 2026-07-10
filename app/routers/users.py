"""用户管理路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import user_service
from ..utils.security import require_auth, require_admin

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
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        data = await user_service.add_user(db, req.model_dump())
        return Result.ok(data, "新增成功")
    except ValueError as e:
        return Result.error(str(e))


@router.put("/sys/user/edit")
async def edit_user(
    req: EditUserRequest,
    id: str = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        await user_service.edit_user(db, id, req.model_dump(exclude_none=True))
        return Result.ok(None, "修改成功")
    except ValueError as e:
        return Result.error(str(e))


@router.delete("/sys/user/delete")
async def delete_user(
    id: str = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        await user_service.delete_user(db, id)
        return Result.ok(None, "删除成功")
    except ValueError as e:
        return Result.error(str(e))


@router.put("/sys/user/adminResetPassword")
async def admin_reset_password(
    req: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """管理员重置任意用户密码（无需旧密码）"""
    try:
        await user_service.reset_user_password(db, req.userId, req.newPassword)
        return Result.ok(None, "密码重置成功")
    except ValueError as e:
        return Result.error(str(e))
