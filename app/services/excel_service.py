"""Shared Excel generation logic for process log and flatness reports."""
import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.chart import BarChart, ScatterChart, Reference, Series  # type: ignore[unresolved-import]
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties

# --- Style constants ---
_THIN_BORDER = Border(
    left=Side(style="thin", color="FF2D3B4F"),
    right=Side(style="thin", color="FF2D3B4F"),
    top=Side(style="thin", color="FF2D3B4F"),
    bottom=Side(style="thin", color="FF2D3B4F"),
)
_FONT_TITLE = Font(name="Microsoft YaHei", bold=True, size=14, color="FF000000")
_FONT_SUBTITLE = Font(name="Microsoft YaHei", size=10, color="FF444444")
_FONT_SECTION = Font(name="Microsoft YaHei", bold=True, size=11, color="FF000000")
_FONT_LABEL = Font(name="Microsoft YaHei", size=10, color="FF000000")
_FONT_VALUE = Font(name="Microsoft YaHei", size=10, bold=True, color="FF000000")
_FONT_UNIT = Font(name="Microsoft YaHei", size=9, color="FF888888")
_FONT_TBL_HDR = Font(name="Microsoft YaHei", bold=True, size=10, color="FF000000")
_FILL_TITLE = PatternFill(start_color="FFFFFFFF", end_color="FFFFFFFF", fill_type="solid")
_FILL_SECTION = PatternFill(start_color="FFF5F5F5", end_color="FFF5F5F5", fill_type="solid")
_FILL_LABEL = PatternFill(start_color="FFFFFFFF", end_color="FFFFFFFF", fill_type="solid")
_FILL_TBL_HDR = PatternFill(start_color="FFF0F0F0", end_color="FFF0F0F0", fill_type="solid")
_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
_ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
_MILLI_THRESHOLD = 1e12


def _ts_str(ts) -> str:
    """Convert timestamp (ms or s) to readable string."""
    if ts is None:
        return "-"
    n = int(ts)
    if n < _MILLI_THRESHOLD:
        n = n * 1000
    try:
        return datetime.fromtimestamp(n / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(ts)


def _num(v, d=2):
    """Format numeric value to given decimal places, or return '-' for None."""
    if v is None:
        return "-"
    try:
        return round(float(v), d)
    except (ValueError, TypeError):
        return str(v)


def safe_filename(name: str) -> str:
    """Sanitize string for use as filename."""
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "unknown"


def _set_cell(ws, row, col, value, font=None, fill=None, align=None, border=None):
    c = ws.cell(row=row, column=col, value=value)
    if font:
        c.font = font
    if fill:
        c.fill = fill
    if align:
        c.alignment = align
    if border:
        c.border = border
    return c


def build_process_log_excel(r) -> bytes:
    """Build a single-blade process log Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "加工日志"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 14

    row = 1
    # Title
    ws.merge_cells(f"A{row}:C{row}")
    _set_cell(ws, row, 1, "螺栓孔加工结果", _FONT_TITLE, _FILL_TITLE, _ALIGN_CENTER, _THIN_BORDER)
    ws.row_dimensions[row].height = 30
    row += 1

    # Subtitle
    ws.merge_cells(f"A{row}:C{row}")
    sub = f"叶片ID：{r.blade_id or '-'}    设备：{r.device_name or '-'}    上报时间：{_ts_str(r.event_time)}"
    _set_cell(ws, row, 1, sub, _FONT_SUBTITLE, None, _ALIGN_LEFT, _THIN_BORDER)
    row += 1

    def _section(title):
        nonlocal row
        ws.merge_cells(f"A{row}:C{row}")
        _set_cell(ws, row, 1, title, _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
        row += 1

    def _kv(label, value, unit=""):
        nonlocal row
        _set_cell(ws, row, 1, label, _FONT_LABEL, _FILL_LABEL, _ALIGN_RIGHT, _THIN_BORDER)
        _set_cell(ws, row, 2, value, _FONT_VALUE, None, _ALIGN_LEFT, _THIN_BORDER)
        _set_cell(ws, row, 3, unit, _FONT_UNIT, None, _ALIGN_CENTER, _THIN_BORDER)
        row += 1

    _section("基本信息")
    _kv("操作员", r.operator or "-")
    _kv("工厂", r.factory or "-")
    _kv("设备", r.device_type_code or r.device_name or "-")
    _kv("加工开始时间", _ts_str(r.process_start_time))
    _kv("加工结束时间", _ts_str(r.process_end_time))
    _kv("总时长", _num(r.total_duration, 1), "Min")

    _section("扫描结果")
    _kv("扫描结果", r.scan_result or "-")
    _kv("螺栓孔最高点", _num(r.bolt_sleeve_max, 3), "mm")
    _kv("螺栓孔最低点", _num(r.bolt_sleeve_min, 3), "mm")
    _kv("Pitch角度", _num(r.pitch_angle, 3), "°")
    _kv("Yaw角度", _num(r.yaw_angle, 3), "°")
    _kv("BCD预估直径", _num(r.bcd_estimate, 3), "mm")
    _kv("加工前平面度", _num(r.before_flatness, 3), "mm")

    _section("铣磨结果")
    _kv("铣磨深度", _num(r.mill_depth, 1), "mm")
    _kv("铣磨圈数", r.mill_cycles if r.mill_cycles is not None else "-")
    _kv("最终结果", r.mill_result or "-")
    _kv("加工后平面度", _num(r.after_flatness, 3), "mm")

    _section("Process Time")
    _kv("调平和支撑耗时", _num(r.adjust_leg_time, 0), "s")
    _kv("激光调整耗时", _num(r.laser_adjust_time, 0), "s")
    _kv("粗扫耗时", _num(r.rough_scan_time, 0), "s")
    _kv("精扫耗时", _num(r.fine_scan_time, 0), "s")
    _kv("铣磨耗时", _num(r.mill_time, 1), "Min")
    _kv("扫描报告耗时", _num(r.scan_report_time, 0), "s")

    _section("铣磨功率")
    _kv("上部单元平均功率", _num(r.upper_avg_power, 2), "%")
    _kv("上部单元最大功率", _num(r.upper_max_power, 2), "%")
    _kv("下部单元平均功率", _num(r.lower_avg_power, 2), "%")
    _kv("下部单元最大功率", _num(r.lower_max_power, 2), "%")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_flatness_sheet(ws, rec, stage_label: str):
    """Write one flatness sheet (before or after) for a single blade record."""
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 39
    ws.column_dimensions["C"].width = 39

    hole_angle = rec.hole_angle or []
    hole_value = rec.hole_value or []

    row = 1
    ws.merge_cells(f"A{row}:C{row}")
    _set_cell(ws, row, 1, f"平面度报表（{stage_label}）", _FONT_TITLE, _FILL_TITLE, _ALIGN_CENTER, _THIN_BORDER)
    ws.row_dimensions[row].height = 30
    row += 1

    ws.merge_cells(f"A{row}:C{row}")
    sub = f"叶片ID：{rec.blade_id or '-'}    设备：{rec.device_name or '-'}    测量时间：{_ts_str(rec.measure_time)}"
    _set_cell(ws, row, 1, sub, _FONT_SUBTITLE, None, _ALIGN_LEFT, _THIN_BORDER)
    row += 1

    # Statistics section
    ws.merge_cells(f"A{row}:C{row}")
    _set_cell(ws, row, 1, "统计数据", _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
    row += 1

    for label, val, unit in [
        ("最大值", _num(rec.max_value, 2), "mm"),
        ("最小值", _num(rec.min_value, 2), "mm"),
        ("峰峰值（P-V值）", _num(rec.pv_value, 2), "mm"),
        ("RMS", _num(rec.rms, 2), "mm"),
    ]:
        _set_cell(ws, row, 1, label, _FONT_LABEL, _FILL_LABEL, _ALIGN_RIGHT, _THIN_BORDER)
        _set_cell(ws, row, 2, val, _FONT_VALUE, None, _ALIGN_LEFT, _THIN_BORDER)
        _set_cell(ws, row, 3, unit, _FONT_UNIT, None, _ALIGN_CENTER, _THIN_BORDER)
        row += 1

    # Chart section
    row += 1
    ws.merge_cells(f"A{row}:C{row}")
    _set_cell(ws, row, 1, "曲线图", _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
    row += 1

    chart_reserved_start = row
    row += 16

    # Measurement data table
    if hole_angle:
        ws.merge_cells(f"A{row}:C{row}")
        _set_cell(ws, row, 1, "测量数据", _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
        row += 1

        for ci, h in enumerate(["#", "孔角度 (°)", "孔测量值 (mm)"], 1):
            _set_cell(ws, row, ci, h, _FONT_TBL_HDR, _FILL_TBL_HDR, _ALIGN_CENTER, _THIN_BORDER)
        row += 1

        data_start_row = row
        for di, angle in enumerate(hole_angle):
            _set_cell(ws, row, 1, di + 1, _FONT_VALUE, None, _ALIGN_CENTER, _THIN_BORDER)
            _set_cell(ws, row, 2, _num(angle, 4), _FONT_VALUE, None, _ALIGN_CENTER, _THIN_BORDER)
            _set_cell(ws, row, 3, _num(hole_value[di] if di < len(hole_value) else None, 4), _FONT_VALUE, None, _ALIGN_CENTER, _THIN_BORDER)
            row += 1
        data_end_row = row - 1

        # Build scatter chart
        chart = ScatterChart()
        chart.width = 19
        chart.height = 8

        chart.graphical_properties = GraphicalProperties()
        chart.graphical_properties.line.noFill = True

        x_vals = Reference(ws, min_col=2, min_row=data_start_row, max_row=data_end_row)
        y_vals = Reference(ws, min_col=3, min_row=data_start_row, max_row=data_end_row)

        series = Series(y_vals, x_vals)
        series.marker.symbol = "circle"
        series.marker.size = 4
        series.marker.graphicalProperties.solidFill = "60C7F3"
        series.graphicalProperties.line.width = 15000
        series.graphicalProperties.line.solidFill = "60C7F3"
        series.smooth = True
        chart.series.append(series)

        # X-axis (horizontal in Excel)
        chart.x_axis.title = "孔测量值 (mm)"
        chart.x_axis.numFmt = '0.0'
        chart.x_axis.crosses = "min"
        chart.x_axis.spPr = GraphicalProperties(ln=LineProperties(solidFill="E3E6EA"))
        chart.x_axis.majorGridlines = ChartLines(  # type: ignore[assignment]
            spPr=GraphicalProperties(ln=LineProperties(solidFill="F2F3F5"))
        )

        # Y-axis (vertical in Excel)
        chart.y_axis.title = "孔角度 (°)"
        chart.y_axis.numFmt = '0.0'
        chart.y_axis.crosses = "min"
        chart.y_axis.spPr = GraphicalProperties(ln=LineProperties(solidFill="E3E6EA"))
        chart.y_axis.majorGridlines = ChartLines(  # type: ignore[assignment]
            spPr=GraphicalProperties(ln=LineProperties(solidFill="F2F3F5"))
        )

        chart.legend = None
        ws.add_chart(chart, f"A{chart_reserved_start}")


def build_flatness_excel(before_rec, after_rec) -> bytes:
    """Build a single-blade flatness Excel with before/after in separate sheets."""
    wb = Workbook()
    wb.remove(wb.active)

    if before_rec:
        ws = wb.create_sheet("加工前")
        _build_flatness_sheet(ws, before_rec, "加工前")
    if after_rec:
        ws = wb.create_sheet("加工后")
        _build_flatness_sheet(ws, after_rec, "加工后")

    if not wb.worksheets:
        wb.create_sheet("无数据")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_flatness_single_excel(rec, stage_label: str) -> bytes:
    """Build a flatness Excel with a single sheet (加工前 or 加工后 only)."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.create_sheet(stage_label)
    ws = wb[stage_label]

    _build_flatness_sheet(ws, rec, stage_label)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================ 统计报表 ============================

def _fmt_pct(v) -> str:
    return "-" if v is None else f"{round(v * 100, 2)}%"


def _fmt_null(v) -> str:
    return "-" if v is None else str(v)


def _report_sheet_header(ws, title: str, subtitle: str) -> int:
    """在给定工作表写入报表标题 + 副标题，返回内容起始行号（第 4 行）。"""
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 18
    ws.merge_cells("A1:E1")
    _set_cell(ws, 1, 1, title, _FONT_TITLE, _FILL_TITLE, _ALIGN_CENTER, _THIN_BORDER)
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:E2")
    _set_cell(ws, 2, 1, subtitle, _FONT_SUBTITLE, None, _ALIGN_LEFT, _THIN_BORDER)
    return 4


def _new_report_workbook(title: str, subtitle: str):
    """Create a workbook + active sheet with a report title and subtitle row."""
    wb = Workbook()
    ws = wb.active
    ws.title = "报表"
    row = _report_sheet_header(ws, title, subtitle)
    return wb, ws, row


def _kv_block(ws, row, kvs):
    for label, value, unit in kvs:
        _set_cell(ws, row, 1, label, _FONT_LABEL, _FILL_LABEL, _ALIGN_RIGHT, _THIN_BORDER)
        _set_cell(ws, row, 2, value, _FONT_VALUE, None, _ALIGN_LEFT, _THIN_BORDER)
        _set_cell(ws, row, 3, unit, _FONT_UNIT, None, _ALIGN_CENTER, _THIN_BORDER)
        row += 1
    return row


def _table_block(ws, row, headers, rows):
    for ci, h in enumerate(headers, 1):
        _set_cell(ws, row, ci, h, _FONT_TBL_HDR, _FILL_TBL_HDR, _ALIGN_CENTER, _THIN_BORDER)
    row += 1
    for r in rows:
        for ci, v in enumerate(r, 1):
            _set_cell(ws, row, ci, v, _FONT_LABEL, None,
                      _ALIGN_CENTER if ci > 1 else _ALIGN_LEFT, _THIN_BORDER)
        row += 1
    return row


def _write_processing_sheet(ws, data: dict, range_label: str, filter_label: str) -> int:
    row = _report_sheet_header(ws, "叶片加工统计报表", f"统计区间：{range_label}    筛选：{filter_label}")
    row = _kv_block(ws, row, [
        ("叶片总数", data.get("total_blades", 0), "片"),
        ("合格数", data.get("qualified", 0), "片"),
        ("合格率", _fmt_pct(data.get("qualification_rate")), ""),
        ("报警次数", data.get("alarm_count", 0), "次"),
        ("平均加工后平面度", _num(data.get("avg_after_flatness"), 3), "mm"),
        ("平均总时长", _num(data.get("avg_total_duration"), 1), "Min"),
        ("OEE（本期仅合格率）", _fmt_pct(data.get("qualification_rate")), "待补可用率/性能率"),
    ])
    row += 1
    ws.merge_cells(f"A{row}:E{row}")
    _set_cell(ws, row, 1, "分设备统计", _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
    row += 1
    row = _table_block(
        ws, row, ["设备", "叶片数", "合格数", "合格率"],
        [[d["device_name"], d["total"], d["qualified"], _fmt_pct(d["qualification_rate"])]
         for d in data.get("per_device", [])],
    )
    return row


def build_processing_report_excel(data: dict, range_label: str, filter_label: str) -> bytes:
    """加工统计报表（合格率 + 报警统计 + OEE合格率维度）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "加工统计"
    _write_processing_sheet(ws, data, range_label, filter_label)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_oee_report_excel(data: dict, range_label: str, filter_label: str) -> bytes:
    """设备 OEE 报告（可用率 × 性能率 × 合格率；本期仅合格率维度）。"""
    wb, ws, row = _new_report_workbook(
        "设备OEE报告", f"统计区间：{range_label}    筛选：{filter_label}"
    )
    o = data.get("overall", {})
    row = _kv_block(ws, row, [
        ("可用率", _fmt_null(o.get("availability")), "待采集"),
        ("性能率", _fmt_null(o.get("performance")), "待采集"),
        ("合格率", _fmt_pct(o.get("qualification_rate")), ""),
        ("OEE", _fmt_null(o.get("oee")), "待采集（可用率×性能率×合格率）"),
        ("总叶片数", o.get("total", 0), "片"),
        ("合格数", o.get("qualified", 0), "片"),
    ])
    row += 1
    ws.merge_cells(f"A{row}:E{row}")
    _set_cell(ws, row, 1, "分设备OEE（本期仅合格率）", _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
    row += 1
    row = _table_block(
        ws, row, ["设备", "叶片数", "合格数", "可用率", "性能率", "合格率", "OEE"],
        [[d["device_name"], d["total"], d["qualified"], _fmt_null(d.get("availability")),
          _fmt_null(d.get("performance")), _fmt_pct(d.get("qualification_rate")), _fmt_null(d.get("oee"))]
         for d in data.get("per_device", [])],
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_model_report_excel(rows: list, range_label: str, filter_label: str) -> bytes:
    """型号统计报表（按 blade_id 前 3 位分组），以表格统计展示（与页面「型号明细」一致），并附各型号叶片数/合格数柱状图。"""
    wb, ws, row = _new_report_workbook(
        "型号统计报表", f"统计区间：{range_label}    筛选：{filter_label}"
    )
    row = _table_block(
        ws, row,
        ["型号（前3位）", "叶片数", "合格数", "合格率", "平均加工后平面度(mm)"],
        [[r["model"], r["total"], r["qualified"], _fmt_pct(r["qualification_rate"]),
          _num(r.get("avg_after_flatness"), 3)] for r in rows],
    )
    if rows:
        _add_model_bar_chart(ws, row, len(rows))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_alarm_top_excel(data: dict, range_label: str, filter_label: str) -> bytes:
    """报警频次 Top10 分析报告。"""
    wb, ws, row = _new_report_workbook(
        "报警频次Top10分析报告", f"统计区间：{range_label}    筛选：{filter_label}"
    )
    row = _kv_block(ws, row, [
        ("告警记录总数（非空）", data.get("total_records", 0), "条"),
        ("不同故障类型", data.get("distinct_faults", 0), "类"),
    ])
    row += 1
    row = _table_block(
        ws, row, ["排名", "故障类型", "出现次数"],
        [[i + 1, it["fault"], it["count"]] for i, it in enumerate(data.get("items", []))],
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- 四合一汇总（单文件包含全部报表） ----
def _write_oee_sheet(ws, data: dict, range_label: str, filter_label: str) -> int:
    row = _report_sheet_header(ws, "设备OEE报告", f"统计区间：{range_label}    筛选：{filter_label}")
    o = data.get("overall", {})
    row = _kv_block(ws, row, [
        ("可用率", _fmt_null(o.get("availability")), "待采集"),
        ("性能率", _fmt_null(o.get("performance")), "待采集"),
        ("合格率", _fmt_pct(o.get("qualification_rate")), ""),
        ("OEE", _fmt_null(o.get("oee")), "待采集（可用率×性能率×合格率）"),
        ("总叶片数", o.get("total", 0), "片"),
        ("合格数", o.get("qualified", 0), "片"),
    ])
    row += 1
    ws.merge_cells(f"A{row}:E{row}")
    _set_cell(ws, row, 1, "分设备OEE（本期仅合格率）", _FONT_SECTION, _FILL_SECTION, _ALIGN_LEFT, _THIN_BORDER)
    row += 1
    row = _table_block(
        ws, row, ["设备", "叶片数", "合格数", "可用率", "性能率", "合格率", "OEE"],
        [[d["device_name"], d["total"], d["qualified"], _fmt_null(d.get("availability")),
          _fmt_null(d.get("performance")), _fmt_pct(d["qualification_rate"]), _fmt_null(d.get("oee"))]
         for d in data.get("per_device", [])],
    )
    return row


def _add_model_bar_chart(ws, end_row: int, n_rows: int) -> None:
    """在型号统计表格下方追加「各型号叶片数 / 合格数」柱状图（数值列，绘图正确）。"""
    if n_rows <= 0:
        return
    hdr_row = end_row - n_rows - 1
    data_start = hdr_row + 1
    data_end = hdr_row + n_rows
    cats = Reference(ws, min_col=1, min_row=data_start, max_row=data_end)

    bar = BarChart()
    bar.type = "col"
    bar.title = "各型号叶片数 / 合格数"
    bar.height = 8
    bar.width = 18
    bar.add_data(Reference(ws, min_col=2, min_row=hdr_row, max_row=data_end), titles_from_data=True)
    bar.add_data(Reference(ws, min_col=3, min_row=hdr_row, max_row=data_end), titles_from_data=True)
    bar.set_categories(cats)
    ws.add_chart(bar, f"A{data_end + 3}")


def _write_model_sheet(ws, rows: list, range_label: str, filter_label: str) -> int:
    row = _report_sheet_header(ws, "型号统计报表", f"统计区间：{range_label}    筛选：{filter_label}")
    row = _table_block(
        ws, row,
        ["型号（前3位）", "叶片数", "合格数", "合格率", "平均加工后平面度(mm)"],
        [[r["model"], r["total"], r["qualified"], _fmt_pct(r["qualification_rate"]),
          _num(r.get("avg_after_flatness"), 3)] for r in rows],
    )
    if rows:
        _add_model_bar_chart(ws, row, len(rows))
    return row


def _write_alarm_sheet(ws, data: dict, range_label: str, filter_label: str) -> int:
    row = _report_sheet_header(ws, "报警频次Top10分析报告", f"统计区间：{range_label}    筛选：{filter_label}")
    row = _kv_block(ws, row, [
        ("告警记录总数（非空）", data.get("total_records", 0), "条"),
        ("不同故障类型", data.get("distinct_faults", 0), "类"),
    ])
    row += 1
    row = _table_block(
        ws, row, ["排名", "故障类型", "出现次数"],
        [[i + 1, it["fault"], it["count"]] for i, it in enumerate(data.get("items", []))],
    )
    return row


def build_all_reports_excel(processing, oee, model_rows, alarm_top,
                            range_label: str, filter_label: str) -> bytes:
    """将加工统计 / OEE / 型号统计 / 报警Top10 整合到一个工作簿（四个工作表）。"""
    wb = Workbook()
    wb.remove(wb.active)
    specs = [
        ("加工统计", _write_processing_sheet, processing),
        ("OEE报告", _write_oee_sheet, oee),
        ("型号统计", _write_model_sheet, model_rows),
        ("报警Top10", _write_alarm_sheet, alarm_top),
    ]
    for sheet_title, writer, payload in specs:
        ws = wb.create_sheet(sheet_title)
        writer(ws, payload, range_label, filter_label)
    if not wb.worksheets:
        wb.create_sheet("无数据")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
