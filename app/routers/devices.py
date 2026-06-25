"""设备管理路由 — /api/iot/admin/device/*"""
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..schemas.response import Result
from ..utils.security import get_current_user
from ..services import device_service

router = APIRouter(tags=["设备管理"])


# ==================== 同步 ====================

@router.post("/iot/admin/device/syncAll")
async def sync_all(db: AsyncSession = Depends(get_db)):
    import traceback, sys
    try:
        count = await device_service.sync_from_jetlinks(db)
        return Result.ok(f"同步完成：设备 {count} 台", "同步成功")
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return Result.error(f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}（无异常信息，请查看服务端控制台）")


@router.post("/iot/admin/device/sync")
async def sync_devices(db: AsyncSession = Depends(get_db)):
    try:
        count = await device_service.sync_from_jetlinks(db)
        return Result.ok(f"成功同步 {count} 台设备")
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/syncProducts")
async def sync_products():
    from ..services.jetlinks_service import jetlinks
    try:
        products = await jetlinks.sync_products()
        return Result.ok(f"成功同步 {len(products)} 个产品")
    except Exception as e:
        return Result.error(str(e))


# ==================== 设备列表（字面路径，必须在 /{device_id} 之前） ====================

@router.get("/iot/admin/device/list")
async def device_list(
    pageNo: int = Query(1, alias="pageNo"),
    pageSize: int = Query(20, alias="pageSize"),
    stateValue: str | None = Query(None, alias="stateValue"),
    name: str | None = Query(None, alias="name"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
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
):
    try:
        print('........................ get here')
        ids = await device_service.get_my_device_ids(db, username or "", targetUsername)
        return Result.ok(list(ids))
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/userDeviceIds/{user_id}")
async def user_device_ids(user_id: str, db: AsyncSession = Depends(get_db)):
    try:
        ids = await device_service.get_user_device_ids(db, user_id)
        return Result.ok(ids)
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/allBindings")
async def all_bindings(db: AsyncSession = Depends(get_db)):
    try:
        data = await device_service.get_all_bindings(db)
        return Result.ok(data)
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/bindUser")
async def bind_user(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        await device_service.bind_user(db, body.get("deviceId"), body.get("userId"))
        return Result.ok(None, "绑定成功")
    except ValueError as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/unbindUser")
async def unbind_user(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        await device_service.unbind_user(db, body.get("deviceId"), body.get("userId"))
        return Result.ok(None, "解绑成功")
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/cleanUserBindings/{user_id}")
async def clean_bindings(user_id: str, db: AsyncSession = Depends(get_db)):
    try:
        n = await device_service.clean_user_bindings(db, user_id)
        return Result.ok(f"已清理 {n} 条绑定")
    except Exception as e:
        return Result.error(str(e))


# ==================== 用户-租户 ====================

@router.post("/iot/admin/device/user/assignTenant")
async def assign_user_tenant(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        await device_service.assign_user_tenant(
            db, body.get("username"), body.get("tenantId")
        )
        return Result.ok(None, "分配成功")
    except ValueError as e:
        return Result.error(str(e))


# ==================== 用户扩展（角色+层级） ====================

@router.get("/iot/admin/device/user/extension/all")
async def all_extensions(db: AsyncSession = Depends(get_db)):
    try:
        data = await device_service.get_all_extensions(db)
        return Result.ok(data)
    except Exception as e:
        return Result.error(str(e))


@router.get("/iot/admin/device/user/extension/{user_id}")
async def get_extension(user_id: str, db: AsyncSession = Depends(get_db)):
    try:
        data = await device_service.get_extension(db, user_id)
        return Result.ok(data)
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/user/extension")
async def save_extension(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        await device_service.save_extension(db, body)
        return Result.ok("ok")
    except Exception as e:
        return Result.error(str(e))


@router.post("/iot/admin/device/user/extension/delete/{user_id}")
async def delete_extension(user_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await device_service.delete_extension(db, user_id)
        return Result.ok("ok")
    except Exception as e:
        return Result.error(str(e))


# ==================== 单个设备操作（参数化路径，必须在所有字面路径之后） ====================

@router.get("/iot/admin/device/{device_id}")
async def device_detail(device_id: str, db: AsyncSession = Depends(get_db)):
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
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        ok = await device_service.assign_to_tenant(db, device_id, body.get("tenantId"))
        return Result.ok(None, "分配成功" if ok else "设备不存在")
    except Exception as e:
        return Result.error(str(e))
