-- ============================================
-- IoT 叶片加工监控平台 - 数据库初始化脚本
-- 共建 7 张表 + 1 条初始化数据
-- 注意: 以下建表使用 IF NOT EXISTS，不会覆盖已有数据
-- ============================================

CREATE DATABASE IF NOT EXISTS `iot` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE `iot`;

-- 1. 用户表（合并了原 extension 角色/层级 + tenant_id）
DROP TABLE IF EXISTS `sys_user`;
CREATE TABLE `sys_user` (
    `id` varchar(64) NOT NULL COMMENT '用户ID',
    `username` varchar(100) NOT NULL COMMENT '用户名',
    `password` varchar(255) NOT NULL COMMENT '密码(bcrypt)',
    `realname` varchar(100) DEFAULT NULL COMMENT '姓名',
    `phone` varchar(20) DEFAULT NULL COMMENT '手机号',
    `status` int(11) DEFAULT 1 COMMENT '状态 1=正常 0=禁用',
    `role_type` varchar(20) NOT NULL DEFAULT 'employee' COMMENT '角色: superadmin/admin/employee',
    `parent_id` varchar(64) DEFAULT NULL COMMENT '上级用户ID',
    `tenant_id` int(11) DEFAULT NULL COMMENT '所属租户ID',
    `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`),
    KEY `idx_parent_id` (`parent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户表';

-- 2. 租户表
DROP TABLE IF EXISTS `sys_tenant`;
CREATE TABLE `sys_tenant` (
    `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '租户ID',
    `name` varchar(100) NOT NULL COMMENT '租户名称',
    `status` int(11) DEFAULT 1 COMMENT '状态 1=正常',
    `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='租户表';

-- 3. 设备表（从 JetLinks 同步）
DROP TABLE IF EXISTS `iot_device`;
CREATE TABLE `iot_device` (
    `id` varchar(64) NOT NULL COMMENT 'JetLinks设备ID',
    `name` varchar(200) NOT NULL COMMENT '设备名称',
    `description` varchar(500) DEFAULT NULL COMMENT '描述',
    `product_id` varchar(64) DEFAULT NULL COMMENT '所属产品ID',
    `product_name` varchar(200) DEFAULT NULL COMMENT '产品名称',
    `state_text` varchar(20) DEFAULT NULL COMMENT '状态文本',
    `state_value` varchar(20) DEFAULT NULL COMMENT '状态值',
    `device_type_text` varchar(50) DEFAULT NULL COMMENT '设备类型名称',
    `device_type_value` varchar(50) DEFAULT NULL COMMENT '设备类型值',
    `photo_url` varchar(500) DEFAULT NULL COMMENT '设备图片URL',
    `registry_time` bigint(20) DEFAULT NULL COMMENT '注册时间戳',
    `create_time_jetlinks` bigint(20) DEFAULT NULL COMMENT 'JetLinks创建时间戳',
    `creator_id` varchar(64) DEFAULT NULL COMMENT '创建者ID',
    `creator_name` varchar(100) DEFAULT NULL COMMENT '创建者名称',
    `tenant_id` int(11) DEFAULT 0 COMMENT '归属租户ID',
    `sync_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '最后同步时间',
    PRIMARY KEY (`id`),
    KEY `idx_product_id` (`product_id`),
    KEY `idx_tenant_id` (`tenant_id`),
    KEY `idx_state` (`state_value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='IoT设备表';

-- 4. 设备-用户绑定表
DROP TABLE IF EXISTS `iot_device_user`;
CREATE TABLE `iot_device_user` (
    `id` varchar(64) NOT NULL COMMENT '主键',
    `device_id` varchar(64) NOT NULL COMMENT '设备ID',
    `user_id` varchar(64) NOT NULL COMMENT '用户ID',
    `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_device_user` (`device_id`, `user_id`),
    KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='IoT设备-用户绑定表';

-- 插入默认租户
INSERT INTO `sys_tenant` (`id`, `name`, `status`) VALUES (0, '平台默认租户', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- ============================================================
-- 5-7. Webhook 事件表（由 FastAPI 启动自动创建，以下仅供手动参考）
-- ============================================================

-- 5. Webhook 推送日志表
CREATE TABLE IF NOT EXISTS `iot_webhook_log` (
    `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '自增ID',
    `device_id` varchar(64) NOT NULL COMMENT '设备ID',
    `device_name` varchar(200) DEFAULT NULL COMMENT '设备名称',
    `event_type` varchar(50) NOT NULL COMMENT '事件类型: process_log_report/flatness_data/...',
    `event_time` bigint(20) DEFAULT NULL COMMENT '事件时间戳(毫秒)',
    `raw_body` text DEFAULT NULL COMMENT '原始请求体JSON',
    `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '推送到达时间',
    PRIMARY KEY (`id`),
    KEY `idx_device_id` (`device_id`),
    KEY `idx_event_type` (`event_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Webhook推送日志表';

-- 6. 叶片加工日志表
CREATE TABLE IF NOT EXISTS `iot_process_log` (
    `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '自增ID',
    `device_id` varchar(64) NOT NULL COMMENT '设备ID',
    `device_name` varchar(200) DEFAULT NULL COMMENT '设备名称',
    `event_time` bigint(20) DEFAULT NULL COMMENT '事件时间戳(毫秒)',
    `blade_id` varchar(100) DEFAULT NULL COMMENT '叶片编号',
    `operator` varchar(100) DEFAULT NULL COMMENT '操作员',
    `process_start_time` bigint(20) DEFAULT NULL COMMENT '加工开始时间',
    `process_end_time` bigint(20) DEFAULT NULL COMMENT '加工结束时间',
    `total_duration` int(11) DEFAULT NULL COMMENT '总时长(ms)',
    `factory` varchar(200) DEFAULT NULL COMMENT '工厂',
    `device_type_code` varchar(100) DEFAULT NULL COMMENT '设备类型编号',
    `scan_result` varchar(50) DEFAULT NULL COMMENT '扫描结果',
    `bolt_sleeve_max` double DEFAULT NULL COMMENT '螺栓套最高点',
    `bolt_sleeve_min` double DEFAULT NULL COMMENT '螺栓套最低点',
    `pitch_angle` double DEFAULT NULL COMMENT 'Pitch角度',
    `yaw_angle` double DEFAULT NULL COMMENT 'Yaw角度',
    `bcd_estimate` bigint(20) DEFAULT NULL COMMENT 'BCD预估',
    `before_flatness` double DEFAULT NULL COMMENT '加工前平面度',
    `mill_depth` double DEFAULT NULL COMMENT '铣磨深度',
    `mill_cycles` int(11) DEFAULT NULL COMMENT '铣磨圈数',
    `mill_result` varchar(50) DEFAULT NULL COMMENT '最终结果',
    `after_flatness` double DEFAULT NULL COMMENT '加工后平面度',
    `adjust_leg_time` bigint(20) DEFAULT NULL COMMENT '调平和支腿耗时(ms)',
    `laser_adjust_time` bigint(20) DEFAULT NULL COMMENT '激光调整耗时(ms)',
    `rough_scan_time` bigint(20) DEFAULT NULL COMMENT '粗扫耗时(ms)',
    `fine_scan_time` bigint(20) DEFAULT NULL COMMENT '精扫耗时(ms)',
    `mill_time` bigint(20) DEFAULT NULL COMMENT '铣磨耗时(ms)',
    `scan_report_time` bigint(20) DEFAULT NULL COMMENT '扫描报告耗时(ms)',
    `upper_avg_power` int(11) DEFAULT NULL COMMENT '上部单元平均功率',
    `upper_max_power` int(11) DEFAULT NULL COMMENT '上部单元最大功率',
    `lower_avg_power` int(11) DEFAULT NULL COMMENT '下部单元平均功率',
    `lower_max_power` int(11) DEFAULT NULL COMMENT '下部单元最大功率',
    `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (`id`),
    KEY `idx_device_id` (`device_id`),
    KEY `idx_blade_id` (`blade_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='叶片加工日志表';

-- 7. 平面度测量数据表
CREATE TABLE IF NOT EXISTS `iot_flatness_data` (
    `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '自增ID',
    `device_id` varchar(64) NOT NULL COMMENT '设备ID',
    `device_name` varchar(200) DEFAULT NULL COMMENT '设备名称',
    `event_time` bigint(20) DEFAULT NULL COMMENT '事件时间戳(毫秒)',
    `measure_time` bigint(20) DEFAULT NULL COMMENT '测量时间',
    `blade_id` varchar(100) DEFAULT NULL COMMENT '叶片编号',
    `max_value` double DEFAULT NULL COMMENT '最大值',
    `min_value` double DEFAULT NULL COMMENT '最小值',
    `pv_value` double DEFAULT NULL COMMENT '峰峰值',
    `rms` double DEFAULT NULL COMMENT '平面度值',
    `hole_angle` json DEFAULT NULL COMMENT '孔角度',
    `hole_value` json DEFAULT NULL COMMENT '孔测量值',
    `process_stage` varchar(50) DEFAULT NULL COMMENT '加工阶段(before/after)',
    `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    PRIMARY KEY (`id`),
    KEY `idx_device_id` (`device_id`),
    KEY `idx_blade_id` (`blade_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='平面度测量数据表';
