"""IoT data router — all endpoints require auth and filter by user's bound devices"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..schemas.response import Result
from ..services.jetlinks_service import jetlinks
from ..services import device_service, webhook_service
from ..utils.security import require_auth

router = APIRouter(tags=["IoT数据"])


async def _get_username_and_devices(
    db: AsyncSession, current_user: dict
) -> tuple[str, set[str]]:
    """Get the device IDs a user is allowed to access.

    Matches the frontend device list filtering logic:
    - superadmin -> all devices
    - regular user -> devices bound to them (including subordinate inheritance)
    """
    username = current_user.get("username", "")
    if not username:
        return "", set()
    ids = await device_service.get_my_device_ids(db, username)
    return username, set(ids)


def _filter_by_devices(
    results: list[dict], allowed_ids: set[str]
) -> list[dict]:
    """Filter result list by allowed device IDs"""
    if not results:
        return results
    if not allowed_ids:
        return []
    return [r for r in results if r.get("_deviceId") in allowed_ids]


# ==================== Aggregation endpoints ====================

@router.get("/iot/device/summary")
@router.get("/agg/device/summary")
async def device_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        _, _ = await _get_username_and_devices(db, current_user)
        data = await jetlinks.get_device_summary()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/device/status")
@router.post("/iot/device/status")
@router.get("/agg/device/status")
@router.post("/agg/device/status")
async def device_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        _, _ = await _get_username_and_devices(db, current_user)
        data = await jetlinks.get_device_status()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/spindle/trend")
@router.post("/iot/spindle/trend")
@router.get("/agg/spindle/trend")
@router.post("/agg/spindle/trend")
async def spindle_trend(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        _, _ = await _get_username_and_devices(db, current_user)
        data = await jetlinks.get_spindle_trend()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/feedrate")
@router.post("/iot/feedrate")
@router.get("/agg/feedrate")
@router.post("/agg/feedrate")
async def feedrate(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        _, _ = await _get_username_and_devices(db, current_user)
        data = await jetlinks.get_feedrate()
        return data
    except Exception as e:
        return {"error": str(e)}


# ==================== Process logs ====================

@router.get("/iot/process-log/blades")
async def process_log_blades(
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List blades for a device — only returns data for user's bound devices"""
    try:
        username, allowed = await _get_username_and_devices(db, current_user)
        blades = await webhook_service.query_process_log_blades(
            db, device_name=deviceName or None
        )
        blades = _filter_by_devices(blades, allowed)
        return {
            "success": True,
            "message": f"Found {len(blades)} logs",
            "results": blades,
            "total": len(blades),
        }
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


@router.get("/iot/process-log/query")
@router.get("/agg/process-log/query")
async def process_log_query(
    bladeId: str = Query("", alias="bladeId"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Query process log detail — only returns data for user's bound devices"""
    try:
        username, allowed = await _get_username_and_devices(db, current_user)

        local_logs = await webhook_service.query_process_logs(
            db, blade_id=bladeId or None
        )
        if local_logs:
            local_logs = _filter_by_devices(local_logs, allowed)
            return {
                "success": True,
                "message": f"Found {len(local_logs)} logs (local)",
                "results": local_logs,
                "data": local_logs,
                "total": len(local_logs),
            }

        data = await jetlinks.query_process_logs(bladeId)
        if data.get("success"):
            filtered = _filter_by_devices(data.get("results", []), allowed)
            data["results"] = filtered
            data["data"] = filtered
            data["total"] = len(filtered)
            if not filtered:
                data["message"] = "No matching blade found"
        return data
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


# ==================== Flatness ====================

@router.get("/iot/flatness/blades")
async def flatness_blades(
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List blade flatness data for a device — only returns data for user's bound devices"""
    try:
        username, allowed = await _get_username_and_devices(db, current_user)
        blades = await webhook_service.query_blade_list(
            db, device_name=deviceName or None
        )
        blades = _filter_by_devices(blades, allowed)
        return {
            "success": True,
            "message": f"Found {len(blades)} blades",
            "results": blades,
            "total": len(blades),
        }
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


@router.get("/iot/flatness/query")
@router.get("/agg/flatness/query")
async def flatness_query(
    bladeId: str = Query("", alias="bladeId"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Query flatness detail — only returns data for user's bound devices"""
    try:
        username, allowed = await _get_username_and_devices(db, current_user)

        local_logs = await webhook_service.query_flatness_data(
            db, blade_id=bladeId or None
        )
        if local_logs:
            local_logs = _filter_by_devices(local_logs, allowed)
            return {
                "success": True,
                "message": f"Found {len(local_logs)} flatness records (local)",
                "results": local_logs,
                "data": local_logs,
                "total": len(local_logs),
            }

        data = await jetlinks.query_flatness(bladeId or None)
        if data.get("success"):
            filtered = _filter_by_devices(data.get("results", []), allowed)
            data["results"] = filtered
            data["data"] = filtered
            data["total"] = len(filtered)
            if not filtered:
                data["message"] = "No matching blade found"
        return data
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


# ==================== Statistics ====================

@router.get("/iot/statistics/flatness")
async def flatness_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Flatness before/after comparison statistics — only for user's bound devices"""
    try:
        username, allowed = await _get_username_and_devices(db, current_user)
        data = await webhook_service.query_flatness_statistics(db)
        data = _filter_by_devices(data, allowed)
        return {
            "success": True,
            "message": f"{len(data)} records",
            "results": data,
            "total": len(data),
        }
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


# ==================== Device proxy (JetLinks pass-through, filtered) ====================

@router.get("/iot/device/list")
async def device_list_jetlinks(
    page: int = Query(1, alias="page"),
    pageSize: int = Query(50, alias="pageSize"),
    status: str | None = Query(None, alias="status"),
    keyword: str | None = Query(None, alias="keyword"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        username, allowed = await _get_username_and_devices(db, current_user)
        data = await jetlinks.get_device_list(page, pageSize, status, keyword)
        devices = data.get("data", [])
        if allowed:
            devices = [d for d in devices if d.get("id") in allowed]
        data["data"] = devices
        data["total"] = len(devices)
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/device/{device_id}")
async def device_detail_jetlinks(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Device detail — only accessible if device is bound to user"""
    try:
        username, allowed = await _get_username_and_devices(db, current_user)
        if allowed and device_id not in allowed:
            return {"error": "Access denied for this device"}
        data = await jetlinks.get_device_detail(device_id)
        return data
    except Exception as e:
        return {"error": str(e)}
