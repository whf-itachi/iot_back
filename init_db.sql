-- ============================================
-- IoT 叶片加工监控平台 - 数据库初始化脚本 (重构版)
-- 4 张表: sys_user, sys_tenant, iot_device, iot_device_user
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
