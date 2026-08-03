"""IoT data router — all endpoints require auth and filter by user's bound devices"""
import io
import zipfile
from datetime import datetime, timedelta
from urllib.parse import quote
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..services.jetlinks_service import jetlinks
from ..services import device_service, webhook_service
from ..services.excel_service import (
    build_process_log_excel,
    build_flatness_excel,
    build_flatness_single_excel,
    safe_filename,
)
from ..utils.security import require_auth
from ..utils.logger import logger

router = APIRouter(tags=["IoT数据"])


async def _get_allowed_device_ids(
    db: AsyncSession, current_user: dict
) -> set[str]:
    """Get the device IDs a user is allowed to access."""
    username = current_user.get("username", "")
    if not username:
        return set()
    return set(await device_service.get_my_device_ids(db, username))


def _filter_by_devices(
    results: list[dict], allowed_ids: set[str]
) -> list[dict]:
    """Filter result list by allowed device IDs"""
    if not results:
        return results
    if not allowed_ids:
        return []
    return [r for r in results if r.get("_deviceId") in allowed_ids]


def _parse_time_range(start_str: str, end_str: str) -> tuple[int | None, int | None]:
    """Convert date strings (YYYY-MM-DD) to ms timestamp range (end is 23:59:59.999)."""
    start_ms = None
    end_ms = None
    if start_str:
        start_dt = datetime.strptime(start_str[:10], "%Y-%m-%d")
        start_ms = int(start_dt.timestamp() * 1000)
    if end_str:
        end_dt = datetime.strptime(end_str[:10], "%Y-%m-%d") + timedelta(days=1) - timedelta(milliseconds=1)
        end_ms = int(end_dt.timestamp() * 1000)
    return start_ms, end_ms


# ==================== Aggregation endpoints ====================

@router.get("/iot/device/summary")
@router.get("/agg/device/summary")
async def device_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        _ = await _get_allowed_device_ids(db, current_user)
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
        _ = await _get_allowed_device_ids(db, current_user)
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
        _ = await _get_allowed_device_ids(db, current_user)
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
        _ = await _get_allowed_device_ids(db, current_user)
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
        allowed = await _get_allowed_device_ids(db, current_user)
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
        allowed = await _get_allowed_device_ids(db, current_user)

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
        allowed = await _get_allowed_device_ids(db, current_user)
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
        allowed = await _get_allowed_device_ids(db, current_user)

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
    device_name: str = Query("", description="按设备名称过滤（精确匹配），留空表示不过滤"),
    blade_name: str = Query("", description="叶片名称（叶片编号）模糊查询，留空查询全部"),
    product: str = Query("", description="按产品筛选（IMM/HRS/DMM），留空表示不过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Flatness before/after comparison statistics — only for user's bound devices, with optional device-name / blade-name / product filtering"""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        data = await webhook_service.query_flatness_statistics(
            db,
            device_name=device_name or None,
            blade_name=blade_name or None,
            product=product or None,
        )
        data = _filter_by_devices(data, allowed)
        return {
            "success": True,
            "message": f"{len(data)} records",
            "results": data,
            "total": len(data),
        }
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0}


@router.get("/iot/statistics/device-detail")
async def device_detail_statistics(
    device_id: str = Query(..., description="设备ID"),
    start_time: str = Query("", description="开始日期 YYYY-MM-DD，为空表示不限"),
    end_time: str = Query("", description="结束日期 YYYY-MM-DD，为空表示不限"),
    blade_name: str = Query("", description="叶片名称（叶片编号）模糊查询，留空查询全部"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """设备加工详情统计 — 仅返回当前用户可访问设备的数据。

    返回该设备下叶片的加工信息汇总：
      1. 加工的叶片数量
      2. 叶片加工前平面度测量结果平均值
      3. 叶片最后加工平面度结果的平均值
      4. 平均铣磨深度
      5. 平均加工时间（分钟）
    字段为空或 0 的叶片不参与对应平均值统计。
    """
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        if allowed and device_id not in allowed:
            return {
                "success": False,
                "message": "无权访问该设备的加工数据",
                "records": [],
                "statistics": None,
                "total": 0,
            }
        start_ms, end_ms = _parse_time_range(start_time, end_time)
        data = await webhook_service.query_device_process_statistics(
            db,
            device_id=device_id,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            blade_keyword=blade_name or None,
        )
        stats = data["statistics"]
        return {
            "success": True,
            "message": f"{stats['blade_count']} blades",
            "records": data["records"],
            "statistics": stats,
            "total": stats["blade_count"],
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "records": [],
            "statistics": None,
            "total": 0,
        }


@router.get("/iot/alarms")
async def device_alarms(
    device_name: str = Query("", description="设备名称模糊查询，留空表示全部所属设备"),
    blade_name: str = Query("", description="叶片名称（叶片编号）精确匹配，留空表示不按叶片筛选"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """告警信息查询 — 仅返回当前用户可访问设备的告警，支持分页。

    联合设备表返回设备名；支持按设备名、叶片名称筛选。
    若按叶片名称筛选，会先核验该叶片是否在候选设备的加工记录中：
    不在则通过 error 字段提示；在则按该叶片加工时间段(process_start~process_end)筛选告警，
    并在 blade_range 中回显叶片加工时间范围。
    """
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        data = await webhook_service.query_device_alarms(
            db,
            allowed_ids=allowed,
            device_name=device_name or None,
            blade_name=blade_name or None,
            page=page,
            page_size=page_size,
        )
        return {
            "success": True,
            "alarms": data["alarms"],
            "blade_range": data["blade_range"],
            "error": data["error"],
            "total": data["total"],
            "page": data["page"],
            "page_size": data["page_size"],
        }
    except Exception as e:
        logger.error(f"查询告警信息失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "alarms": [],
            "blade_range": None,
            "total": 0,
            "page": page,
            "page_size": page_size,
        }


@router.get("/iot/statistics/device-names")
async def statistics_device_names(
    product: str = Query("", description="按产品筛选（IMM/HRS/DMM），留空表示不过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """返回当前用户可访问设备中去重后的设备名称列表（可按产品筛选），供统计页过滤下拉框使用"""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        names = await webhook_service.query_device_names(
            db, allowed_ids=allowed, product=product or None
        )
        return {"success": True, "device_names": names}
    except Exception as e:
        return {"success": False, "message": str(e), "device_names": []}


# ==================== Excel Download ====================


@router.get("/iot/process-log/download")
@router.get("/agg/process-log/download")
async def process_log_download(
    bladeId: str = Query("", alias="bladeId"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Download a single process log Excel by bladeId."""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)

        records = await webhook_service.query_process_logs_exact(
            db, blade_id=bladeId
        )
        if allowed:
            records = [r for r in records if r.device_id in allowed]
        if not records:
            return {"success": False, "message": "未找到该叶片的加工日志记录"}

        r = records[0]
        excel_data = build_process_log_excel(r)
        blade_id = safe_filename(r.blade_id or str(r.id))
        filename = f"加工日志_{blade_id}.xlsx"
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/iot/flatness/download")
@router.get("/agg/flatness/download")
async def flatness_download(
    bladeId: str = Query("", alias="bladeId"),
    stage: str = Query("before", alias="stage"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Download a single-stage flatness Excel by bladeId + stage (before/after)."""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)

        records = await webhook_service.query_flatness_exact(
            db, blade_id=bladeId, process_stage=stage
        )
        if allowed:
            records = [r for r in records if r.device_id in allowed]
        if not records:
            return {"success": False, "message": "未找到该叶片的平面度测量数据"}

        stage_label = "加工后" if stage == "after" else "加工前"
        excel_data = build_flatness_single_excel(records[0], stage_label)
        filename = f"平面度_{safe_filename(bladeId)}_{stage_label}.xlsx"
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== Batch Download ====================


@router.post("/iot/process-log/batch-download")
async def process_log_batch_download(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Batch download process logs — one Excel file per blade, packed as ZIP.

    Request body:
        {
            "deviceNames": ["device1"],
            "startTime": "2026-07-10",   // optional
            "endTime": "2026-07-17"      // optional
        }
    """
    try:
        allowed = await _get_allowed_device_ids(db, current_user)

        device_names = payload.get("deviceNames") or []
        start_str = payload.get("startTime") or ""
        end_str = payload.get("endTime") or ""

        start_ms, end_ms = _parse_time_range(start_str, end_str)

        records = await webhook_service.query_process_logs_for_download(
            db,
            device_names=device_names if device_names else None,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
        )

        if allowed:
            records = [r for r in records if r.device_id in allowed]

        if not records:
            return {"success": False, "message": "所选范围内没有找到加工日志记录"}

        # Build ZIP — one Excel per blade
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            used_names = set()
            for r in records:
                blade_id = safe_filename(r.blade_id or f"unknown_{r.id}")
                fname = f"加工日志_{blade_id}.xlsx"
                # Avoid duplicate filenames
                if fname in used_names:
                    fname = f"加工日志_{blade_id}_{r.id}.xlsx"
                used_names.add(fname)
                excel_data = build_process_log_excel(r)
                zf.writestr(fname, excel_data)

        zip_buf.seek(0)
        filename = f"加工日志_批量_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        encoded = quote(filename)

        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/iot/flatness/batch-download")
async def flatness_batch_download(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Batch download flatness data — one Excel per blade (before+after in separate sheets), packed as ZIP.

    Request body:
        {
            "deviceNames": ["device1"],
            "startTime": "2026-07-10",   // optional
            "endTime": "2026-07-17"      // optional
        }
    """
    try:
        allowed = await _get_allowed_device_ids(db, current_user)

        device_names = payload.get("deviceNames") or []
        start_str = payload.get("startTime") or ""
        end_str = payload.get("endTime") or ""

        start_ms, end_ms = _parse_time_range(start_str, end_str)

        records = await webhook_service.query_flatness_for_download(
            db,
            device_names=device_names if device_names else None,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
        )

        if allowed:
            records = [r for r in records if r.device_id in allowed]

        if not records:
            return {"success": False, "message": "所选范围内没有找到平面度测量数据"}

        # Group by blade_id, each blade may have before + after records
        blade_map: dict[str, dict] = {}
        for r in records:
            bid = r.blade_id or f"unknown_{r.id}"
            if bid not in blade_map:
                blade_map[bid] = {"before": None, "after": None, "_id": r.id}
            stage = (r.process_stage or "before").lower()
            if stage == "after":
                blade_map[bid]["after"] = r
            else:
                blade_map[bid]["before"] = r

        # Build ZIP — one Excel per blade (with before/after sheets)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            used_names = set()
            for bid, info in blade_map.items():
                safe_bid = safe_filename(bid)
                fname = f"平面度_{safe_bid}.xlsx"
                if fname in used_names:
                    fname = f"平面度_{safe_bid}_{info['_id']}.xlsx"
                used_names.add(fname)
                excel_data = build_flatness_excel(info["before"], info["after"])
                zf.writestr(fname, excel_data)

        zip_buf.seek(0)
        filename = f"平面度_批量_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        encoded = quote(filename)

        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


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
        allowed = await _get_allowed_device_ids(db, current_user)
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
        allowed = await _get_allowed_device_ids(db, current_user)
        if allowed and device_id not in allowed:
            return {"error": "Access denied for this device"}
        data = await jetlinks.get_device_detail(device_id)
        return data
    except Exception as e:
        return {"error": str(e)}
