"""初始化 admin 用户 — 运行一次即可"""
import asyncio
import uuid
from app.database import async_session
from app.utils.security import hash_password
from sqlalchemy import select
from app.models.user import SysUser

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "123"


async def main():
    async with async_session() as db:
        result = await db.execute(select(SysUser).where(SysUser.username == ADMIN_USERNAME))
        existing = result.scalar_one_or_none()

        if existing:
            existing.password = hash_password(ADMIN_PASSWORD)
            existing.role_type = "superadmin"
            print(f"用户 admin 已存在，密码已重置为 {ADMIN_PASSWORD}")
        else:
            uid = str(uuid.uuid4()).replace("-", "")[:32]
            db.add(SysUser(
                id=uid, username=ADMIN_USERNAME,
                password=hash_password(ADMIN_PASSWORD),
                realname="超级管理员", role_type="superadmin",
            ))
            print(f"已创建 admin 用户")

        await db.commit()

    print(f"\n初始化完成！用户名: {ADMIN_USERNAME}  密码: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
