"""报表中心路由 — 统计报表（加工统计 / OEE / 型号统计 / 报警Top10）

所有端点均要求登录鉴权，并强制按登录用户可访问的设备集合做数据隔离
（复用 iot 路由的 `_get_allowed_device_ids` / `_parse_time_range`）。

- JSON 端点：供前端页面渲染表格与图表。
- /excel 端点：后端用 openpyxl 生成 xlsx，以 StreamingResponse 流式下载。
"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import report_service
from ..services.excel_service import (
    build_processing_report_excel,
    build_oee_report_excel,
    build_model_report_excel,
    build_alarm_top_excel,
    build_all_reports_excel,
    safe_filename,
    _ts_str,
)
from ..utils.security import require_auth
from .iot import _get_allowed_device_ids, _parse_time_range

router = APIRouter(tags=["报表中心"])

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _range_label(start_ms, end_ms) -> str:
    return f"{_ts_str(start_ms)} ~ {_ts_str(end_ms)}"


def _filter_label(product: str, device_name: str) -> str:
    parts = []
    if product:
        parts.append(f"产品:{product}")
    if device_name:
        parts.append(f"设备:{device_name}")
    return " / ".join(parts) if parts else "全部"


# ==================== 加工统计报表 ====================

@router.get("/iot/reports/processing")
@router.get("/agg/reports/processing")
async def reports_processing(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        data = await report_service.query_processing_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        return {"success": True, **data}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/iot/reports/processing/excel")
async def reports_processing_excel(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        data = await report_service.query_processing_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        excel_data = build_processing_report_excel(
            data, _range_label(start_ms, end_ms), _filter_label(product, deviceName)
        )
        filename = f"加工统计报表_{safe_filename(_ts_str(start_ms))}_{safe_filename(_ts_str(end_ms))}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type=_XLSX_MEDIA,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 设备 OEE 报告 ====================

@router.get("/iot/reports/oee")
@router.get("/agg/reports/oee")
async def reports_oee(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        data = await report_service.query_oee_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        return {"success": True, **data}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/iot/reports/oee/excel")
async def reports_oee_excel(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        data = await report_service.query_oee_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        excel_data = build_oee_report_excel(
            data, _range_label(start_ms, end_ms), _filter_label(product, deviceName)
        )
        filename = f"OEE报告_{safe_filename(_ts_str(start_ms))}_{safe_filename(_ts_str(end_ms))}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type=_XLSX_MEDIA,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 型号统计报表 ====================

@router.get("/iot/reports/model")
@router.get("/agg/reports/model")
async def reports_model(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        rows = await report_service.query_model_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        return {"success": True, "rows": rows}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/iot/reports/model/excel")
async def reports_model_excel(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        rows = await report_service.query_model_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        excel_data = build_model_report_excel(
            rows, _range_label(start_ms, end_ms), _filter_label(product, deviceName)
        )
        filename = f"型号统计报表_{safe_filename(_ts_str(start_ms))}_{safe_filename(_ts_str(end_ms))}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type=_XLSX_MEDIA,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 报警频次 Top10 ====================

@router.get("/iot/reports/alarm-top")
@router.get("/agg/reports/alarm-top")
async def reports_alarm_top(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    top: int = Query(10, alias="top"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        data = await report_service.query_alarm_top(
            db, allowed, start_ms, end_ms, product or None, deviceName or None, top=top
        )
        return {"success": True, **data}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/iot/reports/alarm-top/excel")
async def reports_alarm_top_excel(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    top: int = Query(10, alias="top"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        data = await report_service.query_alarm_top(
            db, allowed, start_ms, end_ms, product or None, deviceName or None, top=top
        )
        excel_data = build_alarm_top_excel(
            data, _range_label(start_ms, end_ms), _filter_label(product, deviceName)
        )
        filename = f"报警频次Top{top}_{safe_filename(_ts_str(start_ms))}_{safe_filename(_ts_str(end_ms))}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type=_XLSX_MEDIA,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 四合一汇总（单文件包含全部报表） ====================

@router.get("/iot/reports/all/excel")
@router.get("/agg/reports/all/excel")
async def reports_all_excel(
    startTime: str = Query("", alias="startTime"),
    endTime: str = Query("", alias="endTime"),
    product: str = Query("", alias="product"),
    deviceName: str = Query("", alias="deviceName"),
    top: int = Query(10, alias="top"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """将加工统计 / OEE / 型号统计 / 报警Top10 整合到一个 xlsx（四个工作表）。"""
    try:
        allowed = await _get_allowed_device_ids(db, current_user)
        start_ms, end_ms = _parse_time_range(startTime, endTime)
        processing = await report_service.query_processing_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        oee = await report_service.query_oee_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        model_rows = await report_service.query_model_statistics(
            db, allowed, start_ms, end_ms, product or None, deviceName or None
        )
        alarm_top = await report_service.query_alarm_top(
            db, allowed, start_ms, end_ms, product or None, deviceName or None, top=top
        )
        excel_data = build_all_reports_excel(
            processing, oee, model_rows, alarm_top,
            _range_label(start_ms, end_ms), _filter_label(product, deviceName)
        )
        filename = f"报表中心_{safe_filename(_ts_str(start_ms))}_{safe_filename(_ts_str(end_ms))}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type=_XLSX_MEDIA,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except Exception as e:
        return {"success": False, "message": str(e)}
