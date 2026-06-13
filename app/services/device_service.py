"""设备管理服务 — 重构版：sys_user 合并了 extension + tenant"""
import uuid
import datetime
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.device import IotDevice
from ..models.device_user import IotDeviceUser
from ..models.user import SysUser
from ..services.jetlinks_service import jetlinks


# ==================== 租户上下文 ====================

async def get_user_tenant_id(db: AsyncSession, username: str) -> int | None:
    """获取用户的租户ID"""
    from .user_service import find_user_id_by_username
    user_id = await find_user_id_by_username(db, username)
    if not user_id:
        return None
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if user.role_type == "superadmin":
        return None
    return user.tenant_id if user.tenant_id and user.tenant_id != 0 else None


async def get_superadmin_id(db: AsyncSession) -> str | None:
    """获取超管的用户ID"""
    result = await db.execute(
        select(SysUser.id).where(SysUser.role_type == "superadmin")
    )
    row = result.first()
    return row[0] if row else None


# ==================== 设备 CRUD ====================

async def get_device_list(
    db: AsyncSession,
    page_no: int = 1,
    page_size: int = 20,
    state_value: str | None = None,
    name: str | None = None,
    tenant_id: int | None = None,
) -> dict:
    """分页查询设备（支持过滤 + 租户隔离）"""
    stmt = select(IotDevice)
    if state_value:
        stmt = stmt.where(IotDevice.state_value == state_value)
    if name:
        stmt = stmt.where(IotDevice.name.like(f"%{name}%"))
    if tenant_id is not None and tenant_id != 0:
        stmt = stmt.where(IotDevice.tenant_id == tenant_id)
    stmt = stmt.order_by(IotDevice.name)

    result = await db.execute(stmt)
    all_devices = result.scalars().all()

    total = len(all_devices)
    start = (page_no - 1) * page_size
    records = all_devices[start: start + page_size]

    return {
        "records": [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "productId": d.product_id,
                "productName": d.product_name,
                "stateText": d.state_text,
                "stateValue": d.state_value,
                "deviceTypeText": d.device_type_text,
                "deviceTypeValue": d.device_type_value,
                "photoUrl": d.photo_url,
                "registryTime": d.registry_time,
                "createTimeJetlinks": d.create_time_jetlinks,
                "tenantId": d.tenant_id,
            }
            for d in records
        ],
        "total": total,
    }


async def get_device_by_id(db: AsyncSession, device_id: str) -> dict | None:
    result = await db.execute(select(IotDevice).where(IotDevice.id == device_id))
    d = result.scalar_one_or_none()
    if not d:
        return None
    return {
        "id": d.id, "name": d.name, "description": d.description,
        "productId": d.product_id, "productName": d.product_name,
        "stateText": d.state_text, "stateValue": d.state_value,
        "tenantId": d.tenant_id, "registryTime": d.registry_time,
    }


async def assign_to_tenant(db: AsyncSession, device_id: str, tenant_id: int | None) -> bool:
    """分配/取消分配设备给租户。取消时级联解绑所有用户"""
    result = await db.execute(select(IotDevice).where(IotDevice.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        return False
    device.tenant_id = tenant_id
    if tenant_id is None or tenant_id == 0:
        await db.execute(delete(IotDeviceUser).where(IotDeviceUser.device_id == device_id))
    await db.commit()
    return True


# ==================== 同步 ====================

async def sync_from_jetlinks(db: AsyncSession) -> int:
    devices = await jetlinks.sync_devices()
    count = 0
    for jd in devices:
        did = jd.get("id")
        if not did:
            continue
        result = await db.execute(select(IotDevice).where(IotDevice.id == did))
        existing = result.scalar_one_or_none()
        state = jd.get("state") or {}
        if existing:
            existing.name = jd.get("name", existing.name)
            existing.description = jd.get("describe", existing.description)
            existing.product_id = jd.get("productId", existing.product_id)
            existing.product_name = jd.get("productName", existing.product_name)
            existing.state_text = state.get("text", existing.state_text)
            existing.state_value = state.get("value", existing.state_value)
            existing.sync_time = datetime.datetime.now()
        else:
            db.add(IotDevice(
                id=did, name=jd.get("name", ""), description=jd.get("describe", ""),
                product_id=jd.get("productId", ""), product_name=jd.get("productName", ""),
                state_text=state.get("text", ""), state_value=state.get("value", ""),
                registry_time=jd.get("registryTime"), create_time_jetlinks=jd.get("createTime"),
                creator_id=jd.get("creatorId", ""), creator_name=jd.get("creatorName", ""),
                tenant_id=0,
            ))
        count += 1
    await db.commit()
    return count


# ==================== 设备-用户绑定 ====================

async def get_my_device_ids(
    db: AsyncSession, username: str, target_username: str | None = None
) -> set[str]:
    """获取操作者可分配的设备ID池

    - 超管 + 目标用户 → 目标用户租户的全部设备
    - 超管 + 无目标 → 全部设备
    - 非超管 → 层级继承（递归向下）
    """
    from .user_service import find_user_id_by_username
    user_id = await find_user_id_by_username(db, username)
    if not user_id:
        return set()

    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    operator = result.scalar_one_or_none()
    if not operator:
        return set()

    if operator.role_type == "superadmin" and target_username:
        return await _get_tenant_devices_for_user(db, target_username)

    if operator.role_type == "superadmin":
        result = await db.execute(select(IotDevice))
        return {d.id for d in result.scalars().all()}

    device_ids: set[str] = set()
    await _add_devices_recursive(db, user_id, device_ids)
    return device_ids


async def _get_tenant_devices_for_user(db: AsyncSession, username: str) -> set[str]:
    from .user_service import find_user_id_by_username
    user_id = await find_user_id_by_username(db, username)
    if not user_id:
        return set()
    tid = await get_user_tenant_id(db, username)
    if tid is None or tid == 0:
        return set()
    result = await db.execute(select(IotDevice.id).where(IotDevice.tenant_id == tid))
    return {row[0] for row in result.all()}


async def _add_devices_recursive(db: AsyncSession, user_id: str, device_ids: set):
    result = await db.execute(
        select(IotDeviceUser).where(IotDeviceUser.user_id == user_id)
    )
    for du in result.scalars().all():
        device_ids.add(du.device_id)
    children = await db.execute(
        select(SysUser).where(SysUser.parent_id == user_id)
    )
    for child in children.scalars().all():
        await _add_devices_recursive(db, child.id, device_ids)


async def get_user_device_ids(db: AsyncSession, user_id: str) -> list[str]:
    result = await db.execute(
        select(IotDeviceUser.device_id).where(IotDeviceUser.user_id == user_id)
    )
    return [row[0] for row in result.all()]


async def get_all_bindings(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(IotDeviceUser))
    bindings = result.scalars().all()
    user_map = {}
    users_result = await db.execute(select(SysUser))
    for u in users_result.scalars().all():
        user_map[u.id] = {"username": u.username, "realname": u.realname}
    return [
        {"device_id": b.device_id, "deviceId": b.device_id,
         "user_id": b.user_id, "userId": b.user_id,
         "username": user_map.get(b.user_id, {}).get("username", ""),
         "realname": user_map.get(b.user_id, {}).get("realname", ""),
        }
        for b in bindings
    ]


async def bind_user(db: AsyncSession, device_id: str, user_id: str) -> None:
    device = await db.execute(select(IotDevice).where(IotDevice.id == device_id))
    if not device.scalar_one_or_none():
        raise ValueError("设备不存在")

    current_uid = user_id
    while current_uid:
        u = await db.execute(select(SysUser).where(SysUser.id == current_uid))
        user = u.scalar_one_or_none()
        if user and user.role_type == "superadmin":
            break
        dup = await db.execute(
            select(IotDeviceUser).where(
                IotDeviceUser.device_id == device_id,
                IotDeviceUser.user_id == current_uid,
            )
        )
        if not dup.scalar_one_or_none():
            db.add(IotDeviceUser(
                id=str(uuid.uuid4()).replace("-", "")[:32],
                device_id=device_id, user_id=current_uid,
            ))
        current_uid = user.parent_id if user else None
    await db.commit()


async def unbind_user(db: AsyncSession, device_id: str, user_id: str) -> None:
    await db.execute(delete(IotDeviceUser).where(
        IotDeviceUser.device_id == device_id, IotDeviceUser.user_id == user_id))
    await db.commit()


async def clean_user_bindings(db: AsyncSession, user_id: str) -> int:
    result = await db.execute(delete(IotDeviceUser).where(IotDeviceUser.user_id == user_id))
    await db.commit()
    return result.rowcount


# ==================== 用户-租户分配 ====================

async def assign_user_tenant(db: AsyncSession, username: str, tenant_id: int) -> None:
    """分配用户到租户"""
    from .user_service import find_user_id_by_username
    user_id = await find_user_id_by_username(db, username)
    if not user_id:
        raise ValueError(f"用户 {username} 不存在")
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.tenant_id = tenant_id
        await db.commit()


# ==================== 用户扩展（角色+层级） ====================

async def get_extension(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"userId": user_id, "parentId": None, "roleType": "employee"}
    role = user.role_type
    if role != "superadmin":
        children = await db.execute(select(SysUser.id).where(SysUser.parent_id == user_id))
        if children.scalars().all():
            role = "admin"
    return {
        "userId": user.id, "parentId": user.parent_id, "parent_id": user.parent_id,
        "roleType": role, "tenantId": user.tenant_id,
    }


async def save_extension(db: AsyncSession, data: dict) -> None:
    """保存用户角色/层级（操作 sys_user 表）"""
    user_id = data.get("userId")
    parent_id = data.get("parentId")
    role_type = data.get("roleType", "employee")

    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return

    # 无上级时默认挂到超管
    if not parent_id and role_type != "superadmin":
        sa_id = await get_superadmin_id(db)
        if sa_id:
            parent_id = sa_id

    user.parent_id = parent_id if parent_id else user.parent_id
    user.role_type = role_type

    # 上级自动升级为 admin
    if parent_id:
        p_result = await db.execute(select(SysUser).where(SysUser.id == parent_id))
        parent = p_result.scalar_one_or_none()
        if parent and parent.role_type not in ("superadmin", "admin"):
            parent.role_type = "admin"

        # 用户的设备复制给上级
        du_result = await db.execute(
            select(IotDeviceUser).where(IotDeviceUser.user_id == user_id))
        for du in du_result.scalars().all():
            dup = await db.execute(select(IotDeviceUser).where(
                IotDeviceUser.device_id == du.device_id,
                IotDeviceUser.user_id == parent_id))
            if not dup.scalar_one_or_none():
                db.add(IotDeviceUser(
                    id=str(uuid.uuid4()).replace("-", "")[:32],
                    device_id=du.device_id, user_id=parent_id))
    await db.commit()


async def get_all_extensions(db: AsyncSession) -> list[dict]:
    """获取所有用户扩展信息（从 sys_user 读取）"""
    result = await db.execute(select(SysUser))
    users = result.scalars().all()
    superadmin_id = await get_superadmin_id(db)

    normalized = []
    for u in users:
        parent = u.parent_id
        # 非超管且无上级 → 归一挂到超管下
        if parent is None and u.role_type != "superadmin" and superadmin_id:
            parent = superadmin_id
        normalized.append({
            "userId": u.id, "user_id": u.id,
            "parentId": parent, "parent_id": parent,
            "roleType": u.role_type, "role_type": u.role_type,
            "username": u.username, "realname": u.realname or "",
        })
    return normalized


async def delete_extension(db: AsyncSession, user_id: str) -> None:
    """重置用户的角色和层级（不删用户，只清空角色字段）"""
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.role_type = "employee"
        user.parent_id = None
        await db.commit()
