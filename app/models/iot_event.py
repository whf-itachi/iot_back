"""IoT 事件记录表 — 接收 JetLinks Webhook 推送的叶片加工日志和平面度测量数据"""
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, DateTime, Float, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class IotWebhookLog(Base):
    """推送日志表 — 记录每次 Webhook 推送的元信息"""

    __tablename__ = "iot_webhook_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True, comment="设备ID")
    device_name: Mapped[str | None] = mapped_column(String(200), comment="设备名称")
    event_type: Mapped[str] = mapped_column(String(50), comment="事件类型")
    event_time: Mapped[int | None] = mapped_column(BigInteger, comment="事件时间戳(毫秒)")
    raw_body: Mapped[str | None] = mapped_column(Text, comment="原始请求体(JSON)")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="推送到达时间")


class IotProcessLog(Base):
    """叶片加工日志 — Webhook 推送 process_log_report 事件"""

    __tablename__ = "iot_process_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="设备ID")
    device_name: Mapped[str | None] = mapped_column(String(200), comment="设备名称")
    event_time: Mapped[int | None] = mapped_column(BigInteger, comment="事件时间戳(毫秒)")

    # 加工日志业务字段
    blade_id: Mapped[str | None] = mapped_column(String(100), index=True, comment="叶片编号")
    operator: Mapped[str | None] = mapped_column(String(100), comment="操作员")
    process_start_time: Mapped[int | None] = mapped_column(BigInteger, comment="加工开始时间")
    process_end_time: Mapped[int | None] = mapped_column(BigInteger, comment="加工结束时间")
    total_duration: Mapped[int | None] = mapped_column(Integer, comment="总时长(ms)")
    factory: Mapped[str | None] = mapped_column(String(200), comment="工厂")
    device_type_code: Mapped[str | None] = mapped_column(String(100), comment="设备类型编号")
    scan_result: Mapped[str | None] = mapped_column(String(50), comment="扫描结果")
    bolt_sleeve_max: Mapped[float | None] = mapped_column(Float, comment="螺栓套最高点")
    bolt_sleeve_min: Mapped[float | None] = mapped_column(Float, comment="螺栓套最低点")
    pitch_angle: Mapped[float | None] = mapped_column(Float, comment="Pitch角度")
    yaw_angle: Mapped[float | None] = mapped_column(Float, comment="Yaw角度")
    bcd_estimate: Mapped[int | None] = mapped_column(BigInteger, comment="BCD预估")
    before_flatness: Mapped[float | None] = mapped_column(Float, comment="加工前平面度")
    mill_depth: Mapped[float | None] = mapped_column(Float, comment="铣磨深度")
    mill_cycles: Mapped[int | None] = mapped_column(Integer, comment="铣磨圈数")
    mill_result: Mapped[str | None] = mapped_column(String(50), comment="最终结果")
    after_flatness: Mapped[float | None] = mapped_column(Float, comment="加工后平面度")
    adjust_leg_time: Mapped[int | None] = mapped_column(BigInteger, comment="调平和支腿耗时(ms)")
    laser_adjust_time: Mapped[int | None] = mapped_column(BigInteger, comment="激光调整耗时(ms)")
    rough_scan_time: Mapped[int | None] = mapped_column(BigInteger, comment="粗扫耗时(ms)")
    fine_scan_time: Mapped[int | None] = mapped_column(BigInteger, comment="精扫耗时(ms)")
    mill_time: Mapped[int | None] = mapped_column(BigInteger, comment="铣磨耗时(ms)")
    scan_report_time: Mapped[int | None] = mapped_column(BigInteger, comment="扫描报告耗时(ms)")
    upper_avg_power: Mapped[int | None] = mapped_column(Integer, comment="上部单元平均功率")
    upper_max_power: Mapped[int | None] = mapped_column(Integer, comment="上部单元最大功率")
    lower_avg_power: Mapped[int | None] = mapped_column(Integer, comment="下部单元平均功率")
    lower_max_power: Mapped[int | None] = mapped_column(Integer, comment="下部单元最大功率")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="入库时间")


class IotFlatnessData(Base):
    """平面度测量数据 — Webhook 推送 flatness_data 事件"""

    __tablename__ = "iot_flatness_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="设备ID")
    device_name: Mapped[str | None] = mapped_column(String(200), comment="设备名称")
    event_time: Mapped[int | None] = mapped_column(BigInteger, comment="事件时间戳(毫秒)")

    # 平面度测量业务字段
    measure_time: Mapped[int | None] = mapped_column(BigInteger, comment="测量时间")
    blade_id: Mapped[str | None] = mapped_column(String(100), index=True, comment="叶片编号")
    max_value: Mapped[float | None] = mapped_column(Float, comment="最大值")
    min_value: Mapped[float | None] = mapped_column(Float, comment="最小值")
    pv_value: Mapped[float | None] = mapped_column(Float, comment="峰峰值")
    rms: Mapped[float | None] = mapped_column(Float, comment="平面度值")
    hole_angle: Mapped[list | None] = mapped_column(JSON, comment="孔角度")
    hole_value: Mapped[list | None] = mapped_column(JSON, comment="孔测量值")
    process_stage: Mapped[str | None] = mapped_column(String(50), comment="加工阶段(before/after)")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="入库时间")
