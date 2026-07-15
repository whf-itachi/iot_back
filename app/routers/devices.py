"""设备管理路由 — /api/iot/admin/device/*"""
from fastapi import APIRouter, Depends, Query, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..schemas.response import Result
from ..utils.security import require_auth, require_admin
from ..utils.ip import get_client_ip
from ..services import device_service, operation_log_service
from ..models.user import SysUser
from ..models.device import IotDevice
from ..models.tenant import SysTenant

router = APIRouter(tags=["设备管理"])


async def _user_label(db: AsyncSession, user_id: str) -> str:
    """获取用户可读标识"""
    if not user_id:
        return "未知用户"
    result = await db.execute(select(SysUser).where(SysUser.id == user_id))
    u = result.scalar_one_or_none()
    return f"{u.username}（{u.realname or ''}）" if u else user_id


async def _device_label(db: AsyncSession, device_id: str) -> str:
    """获取设备可读标识"""
    if not device_id:
        return "未知设备"
    result = await db.execute(select(IotDevice).where(IotDevice.id == device_id))
    d = result.scalar_one_or_none()
    return f"「{d.name}」" if d else device_id


async def _tenant_label(db: AsyncSession, tenant_id: int) -> str:
    """获取租户可读标识"""
    if not tenant_id:
        return "无租户"
    result = await db.execute(select(SysTenant).where(SysTenant.id == tenant_id))
    t = result.scalar_one_or_none()
    return f"「{t.name}」" if t else f"ID:{tenant_id}"


# ==================== 同步 ====================

@router.post("/iot/admin/device/syncAll")
async def sync_all(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    import traceback, sys
    try:
        count = await device_service.sync_from_jetlinks(db)
        return Result.ok(f"同步完成：设备 {count} 台", "同步成功")
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return Result.error(f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}（无异常信息，请查看服务端控制台）")


@router.post("/iot/admin/device/sync")
async def sync_devices(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        count = await device_service.sync_from_jetlinks(db)
        return Result.ok(f"成功同步 {count} 台设备")
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/syncProducts")
async def sync_products(
    _admin: dict = Depends(require_admin),
):
    from ..services.jetlinks_service import jetlinks
    try:
        products = await jetlinks.sync_products()
        return Result.ok(f"成功同步 {len(products)} 个产品")
    except Exception as e:
        return Result.error(str(e))


# ==================== 设备列表（字面路径，必须在 /{device_id} 之前） ====================

@router.get("/iot/admin/device/withBladeData")
async def device_with_blade_data(
    dataType: str = Query("processLog", alias="dataType"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取有叶片加工/平面度数据的设备"""
    try:
        tenant_id: int | None = None
        if current_user and current_user.get("username"):
            tenant_id = await device_service.get_user_tenant_id(db, current_user["username"])
        data = await device_service.get_devices_with_blade_data(db, dataType, tenant_id)
        return Result.ok(data, "查询成功")
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/list")
async def device_list(
    pageNo: int = Query(1, alias="pageNo"),
    pageSize: int = Query(20, alias="pageSize"),
    stateValue: str | None = Query(None, alias="stateValue"),
    name: str | None = Query(None, alias="name"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        # 租户过滤：非超管用户只看自己租户的设备
        tenant_id: int | None = None
        if current_user and current_user.get("username"):
            tenant_id = await device_service.get_user_tenant_id(db, current_user["username"])

        data = await device_service.get_device_list(
            db, pageNo, pageSize, stateValue, name, tenant_id
        )
        return Result.ok(data, "查询成功")
    except Exception as e:
        return Result.error(str(e))


# ==================== 设备-用户绑定（字面路径，必须在 /{device_id} 之前） ====================

@router.get("/iot/admin/device/myDeviceIds")
async def my_device_ids(
    username: str = Query(None, alias="username"),
    targetUsername: str = Query(None, alias="targetUsername"),
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_auth),
):
    try:
        ids = await device_service.get_my_device_ids(db, username or "", targetUsername)
        return Result.ok(list(ids))
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/userDeviceIds/{user_id}")
async def user_device_ids(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        ids = await device_service.get_user_device_ids(db, user_id)
        return Result.ok(ids)
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/allBindings")
async def all_bindings(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        data = await device_service.get_all_bindings(db)
        return Result.ok(data)
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/bindUser")
async def bind_user(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        device_id = body.get("deviceId")
        user_id = body.get("userId")
        # 查名称用于日志
        device_label = await _device_label(db, device_id)
        user_label = await _user_label(db, user_id)
        await device_service.bind_user(db, device_id, user_id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="设备绑定用户",
            detail=f"设备 {device_label} 绑定用户 {user_label}",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "绑定成功")
    except ValueError as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/unbindUser")
async def unbind_user(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        device_id = body.get("deviceId")
        user_id = body.get("userId")
        device_label = await _device_label(db, device_id)
        user_label = await _user_label(db, user_id)
        await device_service.unbind_user(db, device_id, user_id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="设备解绑用户",
            detail=f"设备 {device_label} 解绑用户 {user_label}",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "解绑成功")
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/cleanUserBindings/{user_id}")
async def clean_bindings(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        user_label = await _user_label(db, user_id)
        n = await device_service.clean_user_bindings(db, user_id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="清理用户设备绑定",
            detail=f"清理了用户 {user_label} 的 {n} 条设备绑定",
            ip_address=get_client_ip(request),
        )
        return Result.ok(f"已清理 {n} 条绑定")
    except Exception as e:
        return Result.error(str(e))


# ==================== 用户-租户 ====================

@router.post("/iot/admin/device/user/assignTenant")
async def assign_user_tenant(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        username = body.get("username")
        tenant_id = body.get("tenantId")
        tenant_label = await _tenant_label(db, tenant_id)
        await device_service.assign_user_tenant(db, username, tenant_id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="用户分配租户",
            detail=f"用户 {username} 分配至租户 {tenant_label}",
            ip_address=get_client_ip(request),
        )
        return Result.ok(None, "分配成功")
    except ValueError as e:
        return Result.error(str(e))


# ==================== 用户扩展（角色+层级） ====================

@router.get("/iot/admin/device/user/extension/all")
async def all_extensions(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        data = await device_service.get_all_extensions(db)
        return Result.ok(data)
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/user/extension/{user_id}")
async def get_extension(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_auth),
):
    """查询用户扩展信息（登录后加载角色时调用）"""
    try:
        data = await device_service.get_extension(db, user_id)
        return Result.ok(data)
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/user/extension")
async def save_extension(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        user_id = body.get("userId")
        role_type = body.get("roleType", "employee")
        parent_id = body.get("parentId")
        user_label = await _user_label(db, user_id)
        await device_service.save_extension(db, body)
        detail_parts = [f"保存用户 {user_label} 扩展信息：角色={role_type}"]
        if parent_id:
            parent_label = await _user_label(db, parent_id)
            detail_parts.append(f"上级={parent_label}")
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="保存用户扩展信息",
            detail="，".join(detail_parts),
            ip_address=get_client_ip(request),
        )
        return Result.ok("ok")
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/user/extension/delete/{user_id}")
async def delete_extension(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        user_label = await _user_label(db, user_id)
        await device_service.delete_extension(db, user_id)
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="删除用户扩展信息",
            detail=f"重置了用户 {user_label} 的角色和层级",
            ip_address=get_client_ip(request),
        )
        return Result.ok("ok")
    except Exception as e:
        return Result.error(str(e))


# ==================== 单个设备操作（参数化路径，必须在所有字面路径之后） ====================

@router.get("/iot/admin/device/{device_id}")
async def device_detail(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_auth),
):
    try:
        data = await device_service.get_device_by_id(db, device_id)
        if data:
            return Result.ok(data)
        return Result.error("设备不存在")
    except Exception as e:
        return Result.error(str(e))


@router.put("/iot/admin/device/assign/{device_id}")
async def assign_to_tenant(
    device_id: str,
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        tenant_id = body.get("tenantId")
        device_label = await _device_label(db, device_id)
        ok = await device_service.assign_to_tenant(db, device_id, tenant_id)
        detail = f"设备 {device_label} "
        if tenant_id:
            tenant_label = await _tenant_label(db, tenant_id)
            detail += f"分配至租户 {tenant_label}"
        else:
            detail += "取消租户分配"
        await operation_log_service.create_log(
            db, account=_admin.get("username", ""), operation_type="设备分配租户",
            detail=detail, ip_address=get_client_ip(request),
        )
        return Result.ok(None, "分配成功" if ok else "设备不存在")
    except Exception as e:
        return Result.error(str(e))
