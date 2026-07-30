"""用户管理路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, model_validator
from ..database import get_db
from ..schemas.response import Result
from ..services import user_service, operation_log_service
from ..models.user import SysUser
from ..utils.security import require_auth, require_admin, check_in_my_chain
from ..utils.ip import get_client_ip

router = APIRouter(tags=["用户管理"])


class AddUserRequest(BaseModel):
    username: str
    password: str = "123456"
    realname: str = ""
    parentId: str | None = None
    tenantId: int | None = None
    roleType: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty(cls, data: object) -> object:
        # 前端下拉「不分配 / 无上级」会传空字符串，统一转为 None
        if isinstance(data, dict):
            for k in ("parentId", "tenantId"):
                if data.get(k) in ("", None):
                    data[k] = None
        return data

class EditUserRequest(BaseModel):
    password: str | None = None


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
        payload = req.model_dump()
        # 非超管新增的用户必须挂到自己名下，否则后续 assignTenant / 编辑 / 删除
        # 的权限链检查（check_in_my_chain）会判定“该用户不在您名下”而 403。
        if _admin.get("role") != "superadmin":
            payload["parentId"] = _admin.get("sub")
        result = await user_service.add_user(db, payload)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="新增用户",
            detail=f"新增用户 {req.username}（{req.realname or '未填姓名'}）",
            ip_address=get_client_ip(request),
        )
        return Result.ok(result, "新增成功")
    except ValueError as e:
        return Result.error(str(e))


@router.put("/sys/user/edit")
async def edit_user(
    req: EditUserRequest,
    request: Request,
    id: str = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """编辑用户：仅支持重置密码。超管可操作所有人；其他人只能操作名下（下级）用户。姓名/租户/上级不可在此修改。"""
    await check_in_my_chain(db, current_user, id)

    try:
        result = await db.execute(select(SysUser).where(SysUser.id == id))
        user = result.scalar_one_or_none()
        label = _user_label(user)

        if req.password is None:
            return Result.ok(None, "无变更")

        await user_service.edit_user(db, id, {"password": req.password})
        await operation_log_service.create_log(
            db, account=current_user.get("username", ""), operation_type="编辑用户",
            detail=f"编辑用户 {label}：重置了密码",
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
    current_user: dict = Depends(require_auth),
):
    try:
        await check_in_my_chain(db, current_user, id)
        result = await db.execute(select(SysUser).where(SysUser.id == id))
        user = result.scalar_one_or_none()
        label = _user_label(user)
        await user_service.delete_user(db, id)
        await operation_log_service.create_log(
            db, account=current_user.get("username", ""), operation_type="删除用户",
            detail=f"删除用户 {label}",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "删除成功")
    except ValueError as e:
        return Result.error(str(e))

