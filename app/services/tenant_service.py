"""租户管理服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.tenant import SysTenant


async def get_tenant_list(db: AsyncSession, page_no: int = 1, page_size: int = 200) -> dict:
    """分页查询租户列表"""
    stmt = select(SysTenant).order_by(SysTenant.id)
    result = await db.execute(stmt)
    all_tenants = result.scalars().all()

    total = len(all_tenants)
    start = (page_no - 1) * page_size
    records = all_tenants[start: start + page_size]

    return {
        "records": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "createTime": t.create_time.isoformat() if t.create_time else None,
            }
            for t in records
        ],
        "total": total,
    }


async def add_tenant(db: AsyncSession, data: dict) -> dict:
    """新增租户"""
    tenant = SysTenant(name=data["name"], status=data.get("status", 1))
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return {"id": tenant.id}


async def edit_tenant(db: AsyncSession, tenant_id: int, data: dict) -> None:
    """编辑租户"""
    result = await db.execute(select(SysTenant).where(SysTenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise ValueError("租户不存在")
    if "name" in data:
        tenant.name = data["name"]
    await db.commit()


async def delete_tenant(db: AsyncSession, tenant_id: int) -> None:
    """删除租户"""
    result = await db.execute(select(SysTenant).where(SysTenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise ValueError("租户不存在")
    await db.delete(tenant)
    await db.commit()
