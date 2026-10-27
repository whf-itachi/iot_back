"""IoT data router — all endpoints require auth and filter by user's bound devices"""
import io
import zipfile
from datetime import datetime, timedelta
from urllib.parse import quote
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
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
) -> set[str] | None:
    """获取当前用户可访问的设备ID集合。

    返回 None 表示「无设备范围限制」（超管）：查询 SQL 不应追加 device_id 过滤，
    以避免对全量设备拼出巨型 IN 列表。非超管返回其名下（含下级）设备ID集合；
    若无可访问设备则返回空集 set()（语义：无可用数据）。
    """
    if current_user.get("role") == "superadmin":
        return None
    username = current_user.get("username", "")
    if not username:
        return set()
    return set(await device_service.get_my_device_ids(db, username))


def _filter_by_devices(
    results: list[dict], allowed_ids: set[str] | None
) -> list[dict]:
    """按允许的设备ID集合过滤结果列表（后置兜底，与 SQL 层 device_filter 双重保险）。

    allowed_ids 为 None 表示无限制（超管），直接返回原结果。
    """
    if not results:
        return results
    if allowed_ids is None:
        return results
    if not allowed_ids:
        return []
    return [r for r in results if r.get("_deviceId") in allowed_ids]


async def _build_device_filter(
    db: AsyncSession,
    current_user: dict,
    device_name: str | None = None,
    device_names: list[str] | None = None,
    product: str | None = None,
) -> tuple[set[str] | None, set[str] | None]:
    """构造下推到 SQL 的设备过滤集合 device_filter，以及用于后置过滤的 allowed。

    - allowed：用户可访问设备集合（超管为 None）。
    - explicit：由 device_name / device_names / product 解析出的设备ID集合（无显式过滤则为 None）。
      产品（product）只是设备的描述属性，此处统一解析成设备集合，查询按 device_id 进行。
    - device_filter：最终下推到 SQL 的 device_id 集合；None 表示不加设备谓词（超管且无显式过滤），
      空集表示「过滤后无设备」直接返回空。
    """
    allowed = await _get_allowed_device_ids(db, current_user)
    explicit = await device_service.resolve_device_ids(
        db, device_name=device_name, device_names=device_names, product=product
    )
    if explicit is not None:
        device_filter = explicit if allowed is None else (explicit & allowed)
    else:
        device_filter = allowed
    return device_filter, allowed


def _parse_time_range(start_str: str, end_str: str) -> tuple[int, int]:
    """Convert date strings (YYYY-MM-DD) to ms timestamp range.

    防御性默认（避免无边界全表扫描）：
      - 开始时间为空 → 一年前的此刻
      - 结束时间为空 → 现在
    end 显式传入时取当天 23:59:59.999（闭区间含当天）。
    """
    now = datetime.now()
    if start_str:
        start_dt = datetime.strptime(start_str[:10], "%Y-%m-%d")
    else:
        start_dt = datetime(now.year - 1, now.month, now.day, 0, 0, 0)
    if end_str:
        end_dt = datetime.strptime(end_str[:10], "%Y-%m-%d") + timedelta(days=1) - timedelta(milliseconds=1)
    else:
        end_dt = now
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


# ==================== Process logs ====================

@router.get("/iot/process-log/blades")
async def process_log_blades(
    deviceName: str = Query("", alias="deviceName"),
    page: int = Query(1, ge=1, description="页码，从 1 开始；第 1 页为最新一页"),
    pageSize: int = Query(20, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List blades for a device — 后端分页，仅返回当前用户绑定设备的数据"""
    try:
        device_filter, _ = await _build_device_filter(db, current_user, device_name=deviceName or None)
        res = await webhook_service.query_process_log_blades(db, device_filter=device_filter, page=page, page_size=pageSize)
        return {
            "success": True,
            "message": f"Found {len(res['items'])} logs",
            "results": res["items"],
            "total": res["total"],
            "page": page,
            "pageSize": pageSize,
        }
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0, "page": page, "pageSize": pageSize}


# ==================== Flatness ====================

@router.get("/iot/flatness/blades")
async def flatness_blades(
    deviceName: str = Query("", alias="deviceName"),
    page: int = Query(1, ge=1, description="页码，从 1 开始；第 1 页为最新一页"),
    pageSize: int = Query(20, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List blade flatness data for a device — 后端分页，仅返回当前用户绑定设备的数据"""
    try:
        device_filter, _ = await _build_device_filter(db, current_user, device_name=deviceName or None)
        res = await webhook_service.query_blade_list(db, device_filter=device_filter, page=page, page_size=pageSize)
        return {
            "success": True,
            "message": f"Found {len(res['items'])} blades",
            "results": res["items"],
            "total": res["total"],
            "page": page,
            "pageSize": pageSize,
        }
    except Exception as e:
        return {"success": False, "message": str(e), "results": [], "total": 0, "page": page, "pageSize": pageSize}


# ==================== Detail (by primary key id) ====================
# 列表接口只返回摘要 + 主键 id；点击详情时按 id 单独请求完整记录，避免列表 payload 膨胀。

@router.get("/iot/process-log/detail/{log_id}")
async def process_log_detail(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """按 IotProcessLog 主键 id 获取单条加工日志详情（完整字段）。仅返回当前用户名下设备的数据。"""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        detail = await webhook_service.query_process_log_by_id(db, log_id)
        if not detail:
            return {"success": False, "message": "记录不存在", "data": None}
        # 设备隔离兜底：越权返回空
        if allowed is not None and detail.get("_deviceId") not in allowed:
            return {"success": False, "message": "无权访问该记录", "data": None}
        return {"success": True, "data": detail}
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}


@router.get("/iot/flatness/detail/{flatness_id}")
async def flatness_detail(
    flatness_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """按 IotFlatnessData 主键 id 获取单条平面度测量详情（完整字段，含 hole_angle/hole_value）。仅返回当前用户名下设备的数据。"""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        detail = await webhook_service.query_flatness_by_id(db, flatness_id)
        if not detail:
            return {"success": False, "message": "记录不存在", "data": None}
        if allowed is not None and detail.get("_deviceId") not in allowed:
            return {"success": False, "message": "无权访问该记录", "data": None}
        return {"success": True, "data": detail}
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}


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
        device_filter, allowed = await _build_device_filter(
            db, current_user, device_name=device_name or None, product=product or None
        )
        data = await webhook_service.query_flatness_statistics(
            db,
            device_filter=device_filter,
            blade_name=blade_name or None,
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
    start_time: str = Query("", description="开始日期 YYYY-MM-DD，为空默认近一年"),
    end_time: str = Query("", description="结束日期 YYYY-MM-DD，为空默认现在"),
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
async def process_log_download(
    bladeId: str = Query("", alias="bladeId"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Download a single process log Excel by bladeId.

    设备隔离 + 同名叶片区分：deviceName 为空时在该用户全部设备内查该叶片（取最新一条）；
    传入 deviceName 时精确下推到该设备，避免多台设备同名叶片互相覆盖。
    """
    try:
        device_filter, _ = await _build_device_filter(
            db, current_user, device_names=[deviceName] if deviceName else None
        )

        records = await webhook_service.query_process_logs_exact(
            db, blade_id=bladeId, device_ids=device_filter
        )
        if not records:
            return {"success": False, "message": "未找到该叶片的加工日志记录"}

        r = records[0]
        excel_data = build_process_log_excel(r)
        dev_label = safe_filename(r.device_name or r.device_id or "unknown")
        blade_id = safe_filename(r.blade_id or str(r.id))
        filename = f"加工日志_{dev_label}_{blade_id}.xlsx"
        encoded = quote(filename)

        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/iot/flatness/download")
async def flatness_download(
    bladeId: str = Query("", alias="bladeId"),
    stage: str = Query("before", alias="stage"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Download a single-stage flatness Excel by bladeId + stage (before/after).

    设备隔离 + 同名叶片区分：deviceName 为空时在该用户全部设备内查该叶片（取最新一条）；
    传入 deviceName 时精确下推到该设备，避免多台设备同名叶片互相覆盖。
    """
    try:
        device_filter, _ = await _build_device_filter(
            db, current_user, device_names=[deviceName] if deviceName else None
        )

        records = await webhook_service.query_flatness_exact(
            db, blade_id=bladeId, process_stage=stage, device_ids=device_filter
        )
        if not records:
            return {"success": False, "message": "未找到该叶片的平面度测量数据"}

        stage_label = "加工后" if stage == "after" else "加工前"
        excel_data = build_flatness_single_excel(records[0], stage_label)
        r = records[0]
        dev_label = safe_filename(r.device_name or r.device_id or "unknown")
        filename = f"平面度_{dev_label}_{safe_filename(bladeId)}_{stage_label}.xlsx"
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
            "startTime": "2026-07-10",   // 可选，缺省默认近一年（防御性边界）
            "endTime": "2026-07-17",     // 可选，缺省默认现在
            "bladeName": "B001"          // optional, fuzzy match on blade_id
        }
    """
    try:
        device_names = payload.get("deviceNames") or []
        start_str = payload.get("startTime") or ""
        end_str = payload.get("endTime") or ""
        blade_name = (payload.get("bladeName") or "").strip()

        start_ms, end_ms = _parse_time_range(start_str, end_str)

        device_filter, allowed = await _build_device_filter(
            db, current_user, device_names=device_names if device_names else None
        )

        records = await webhook_service.query_process_logs_for_download(
            db,
            device_filter=device_filter,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            blade_name=blade_name if blade_name else None,
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
                dev_label = safe_filename(r.device_name or r.device_id or "unknown")
                blade_id = safe_filename(r.blade_id or f"unknown_{r.id}")
                fname = f"加工日志_{dev_label}_{blade_id}.xlsx"
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
            "startTime": "2026-07-10",   // 可选，缺省默认近一年（防御性边界）
            "endTime": "2026-07-17",     // 可选，缺省默认现在
            "bladeName": "B001"          // optional, fuzzy match on blade_id
        }
    """
    try:
        device_names = payload.get("deviceNames") or []
        start_str = payload.get("startTime") or ""
        end_str = payload.get("endTime") or ""
        blade_name = (payload.get("bladeName") or "").strip()

        start_ms, end_ms = _parse_time_range(start_str, end_str)

        device_filter, allowed = await _build_device_filter(
            db, current_user, device_names=device_names if device_names else None
        )

        records = await webhook_service.query_flatness_for_download(
            db,
            device_filter=device_filter,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            blade_name=blade_name if blade_name else None,
        )

        if allowed:
            records = [r for r in records if r.device_id in allowed]

        if not records:
            return {"success": False, "message": "所选范围内没有找到平面度测量数据"}

        # 按 (device_id, blade_id) 分组；同名叶片在不同设备上是不同个体，必须区分，否则会被合并甚至丢失。
        blade_map: dict[tuple[str, str], dict] = {}
        for r in records:
            bid = r.blade_id or f"unknown_{r.id}"
            key = (r.device_id, bid)
            if key not in blade_map:
                blade_map[key] = {"before": None, "after": None, "_id": r.id}
            stage = (r.process_stage or "before").lower()
            if stage == "after":
                blade_map[key]["after"] = r
            else:
                blade_map[key]["before"] = r

        # Build ZIP — one Excel per (device, blade) (with before/after sheets)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            used_names = set()
            for (dev_id, bid), info in blade_map.items():
                r0 = info.get("before") or info.get("after")
                dev_label = safe_filename((r0.device_name if r0 else None) or dev_id or "unknown")
                safe_bid = safe_filename(bid)
                fname = f"平面度_{dev_label}_{safe_bid}.xlsx"
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