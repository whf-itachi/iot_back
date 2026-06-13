"""租户管理路由"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import tenant_service

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
):
    try:
        data = await tenant_service.get_tenant_list(db, pageNo, pageSize)
        return Result.ok(data, "查询成功")
    except Exception as e:
        return Result.error(str(e))


@router.post("/sys/tenant/add")
async def add_tenant(req: AddTenantRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = await tenant_service.add_tenant(db, req.model_dump())
        return Result.ok(data, "新增成功")
    except Exception as e:
        return Result.error(str(e))


@router.put("/sys/tenant/edit")
async def edit_tenant(
    req: EditTenantRequest,
    id: int = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
):
    try:
        await tenant_service.edit_tenant(db, id, req.model_dump())
        return Result.ok(None, "修改成功")
    except ValueError as e:
        return Result.error(str(e))


@router.delete("/sys/tenant/delete")
async def delete_tenant(
    id: int = Query(..., alias="id"),
    db: AsyncSession = Depends(get_db),
):
    try:
        await tenant_service.delete_tenant(db, id)
        return Result.ok(None, "删除成功")
    except ValueError as e:
        return Result.error(str(e))
