"""租户管理路由"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import tenant_service, operation_log_service
from ..models.tenant import SysTenant
from ..utils.security import require_auth, require_admin
from ..utils.ip import get_client_ip

router = APIRouter(tags=["租户管理"])


class AddTenantRequest(BaseModel):
    name: str
    status: int = 1


class EditTenantRequest(BaseModel):
    name: str


@router.get("/sys/tenant/list")
async def list_tenants(
    pageNo: int = Query(1, alias="pageNo"),
    pageSize: int = Query(200, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_auth),
):
    try:
        data = await tenant_service.get_tenant_list(db, pageNo, pageSize)
        return Result.ok(data, "查询成功")
    except Exception as e:
        return Result.error(str(e))


@router.post("/sys/tenant/add")
async def add_tenant(
    req: AddTenantRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        data = await tenant_service.add_tenant(db, req.model_dump())
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="新增租户",
            detail=f"新增租户「{req.name}」",
            ip_address=get_client_ip(request),
        )
        return Result.ok(data, "新增成功")
    except Exception as e:
        return Result.error(str(e))


@router.put("/sys/tenant/edit")
async def edit_tenant(
    req: EditTenantRequest,
    request: Request,
    id: int = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        # 先查旧名称
        old_result = await db.execute(select(SysTenant).where(SysTenant.id == id))
        old = old_result.scalar_one_or_none()
        old_name = old.name if old else f"ID:{id}"
        await tenant_service.edit_tenant(db, id, req.model_dump())
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="编辑租户",
            detail=f"修改租户「{old_name}」名称为「{req.name}」",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "修改成功")
    except ValueError as e:
        return Result.error(str(e))


@router.delete("/sys/tenant/delete")
async def delete_tenant(
    request: Request,
    id: int = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        # 先查租户信息（删之前拿到名称）
        old_result = await db.execute(select(SysTenant).where(SysTenant.id == id))
        old = old_result.scalar_one_or_none()
        label = f"「{old.name}」[ID:{id}]" if old else f"[ID:{id}]"
        await tenant_service.delete_tenant(db, id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="删除租户",
            detail=f"删除租户 {label}",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "删除成功")
    except ValueError as e:
        return Result.error(str(e))
