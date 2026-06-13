"""IoT 数据路由 — JetLinks 设备数据代理与聚合"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..schemas.response import Result
from ..services.jetlinks_service import jetlinks
from ..services import device_service

router = APIRouter(tags=["IoT数据"])


async def _filter_by_user_devices(
    db: AsyncSession, username: str, results: list[dict]
) -> list[dict]:
    """过滤结果，只保留用户有权访问的设备数据"""
    if not username or not results:
        return results
    allowed = await device_service.get_my_device_ids(db, username)
    if not allowed:
        return []
    return [r for r in results if r.get("_deviceId") in allowed]


# ==================== 聚合接口（同时支持 /iot/* 和 /agg/*） ====================

@router.get("/iot/device/summary")
@router.get("/agg/device/summary")
async def device_summary():
    try:
        data = await jetlinks.get_device_summary()
        return data  # 直接返回数据，前端用 fetch 直接拿 JSON
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/device/status")
@router.post("/iot/device/status")
@router.get("/agg/device/status")
@router.post("/agg/device/status")
async def device_status():
    try:
        data = await jetlinks.get_device_status()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/spindle/trend")
@router.post("/iot/spindle/trend")
@router.get("/agg/spindle/trend")
@router.post("/agg/spindle/trend")
async def spindle_trend():
    try:
        data = await jetlinks.get_spindle_trend()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/feedrate")
@router.post("/iot/feedrate")
@router.get("/agg/feedrate")
@router.post("/agg/feedrate")
async def feedrate():
    try:
        data = await jetlinks.get_feedrate()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/process-log/query")
@router.get("/agg/process-log/query")
async def process_log_query(
    bladeId: str = Query("", alias="bladeId"),
    username: str = Query(None, alias="username"),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await jetlinks.query_process_logs(bladeId)
        if data.get("success") and username:
            filtered = await _filter_by_user_devices(db, username, data.get("results", []))
            data["results"] = filtered
            data["data"] = filtered
            data["total"] = len(filtered)
            if not filtered:
                data["message"] = "查无此叶片信息"
        return data
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


@router.get("/iot/flatness/query")
@router.get("/agg/flatness/query")
async def flatness_query(
    bladeId: str = Query("", alias="bladeId"),
    username: str = Query(None, alias="username"),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await jetlinks.query_flatness(bladeId or None)
        if data.get("success") and username:
            filtered = await _filter_by_user_devices(db, username, data.get("results", []))
            data["results"] = filtered
            data["data"] = filtered
            data["total"] = len(filtered)
            if not filtered:
                data["message"] = "查无此叶片信息"
        return data
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


@router.get("/iot/device/list")
async def device_list_jetlinks(
    page: int = Query(1, alias="page"),
    pageSize: int = Query(50, alias="pageSize"),
    status: str | None = Query(None, alias="status"),
    keyword: str | None = Query(None, alias="keyword"),
):
    try:
        data = await jetlinks.get_device_list(page, pageSize, status, keyword)
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/iot/device/{device_id}")
async def device_detail_jetlinks(device_id: str):
    try:
        data = await jetlinks.get_device_detail(device_id)
        return data
    except Exception as e:
        return {"error": str(e)}
