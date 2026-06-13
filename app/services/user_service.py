"""用户管理服务 — 重构版"""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.user import SysUser
from ..utils.security import hash_password


async def get_user_list(db: AsyncSession, page_no: int = 1, page_size: int = 200) -> dict:
    stmt = select(SysUser).order_by(SysUser.create_time.desc())
    result = await db.execute(stmt)
    all_users = result.scalars().all()
    total = len(all_users)
    start = (page_no - 1) * page_size
    records = all_users[start: start + page_size]

    return {
        "records": [
            {
                "id": u.id, "username": u.username, "realname": u.realname,
                "phone": u.phone, "status": u.status,
                "relTenantIds": str(u.tenant_id) if u.tenant_id else None,
                "createTime": u.create_time.isoformat() if u.create_time else None,
            }
            for u in records
        ],
        "total": total,
    }


async def add_user(db: AsyncSession, data: dict) -> dict:
    result = await db.execute(select(SysUser).where(SysUser.username == data["username"]))
    if result.scalar_one_or_none():
        raise ValueError(f"用户名 {data['username']} 已存在")

    uid = str(uuid.uuid4()).replace("-", "")[:32]
    user = SysUser(
        id=uid,
        username=data["username"],
        password=hash_password(data.get("password", "123456")),
        realname=data.get("realname", ""),
        phone=data.get("phone", ""),
        status=1,
    )
    db.add(user)
    await db.commit()
    return {"id": uid}


async def edit_user(db: AsyncSession, user_id: str, data: dict) -> None:
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")
    if "realname" in data:
        user.realname = data["realname"]
    if "phone" in data:
        user.phone = data["phone"]
    if "password" in data and data["password"]:
        user.password = hash_password(data["password"])
    await db.commit()


async def delete_user(db: AsyncSession, user_id: str) -> None:
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")
    await db.delete(user)
    await db.commit()


async def find_user_id_by_username(db: AsyncSession, username: str) -> str | None:
    result = await db.execute(select(SysUser.id).where(SysUser.username == username))
    row = result.first()
    return row[0] if row else None
