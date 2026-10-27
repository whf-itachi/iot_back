# IoT Backend — 叶片加工监控平台后端

基于 **FastAPI** 的 IoT 叶片加工监控系统后端，提供用户认证、设备管理、租户管理、JetLinks 对接等 API 服务。

## 技术栈

| 技术          | 版本    | 用途                    |
| ----------- | ----- | --------------------- |
| FastAPI     | 0.115 | Web 框架                |
| Uvicorn     | 0.34  | ASGI 服务器              |
| SQLAlchemy  | 2.0   | ORM（异步模式）             |
| aiomysql    | 0.2   | MySQL 异步驱动            |
| Pydantic    | 2.10  | 数据校验 & 配置管理           |
| python-jose | 3.3   | JWT 令牌处理              |
| passlib     | 1.7   | 密码哈希                  |
| httpx       | 0.28  | HTTP 客户端（对接 JetLinks） |

## 项目结构

```
iot_back/
├── app/
│   ├── main.py              # FastAPI 应用入口（CORS、路由注册、生命周期 create_all 建表）
│   ├── config.py            # 配置管理（pydantic-settings，从 .env 读取）
│   ├── database.py          # 数据库连接（SQLAlchemy 异步引擎 + session）
│   ├── models/              # ORM 模型
│   │   ├── user.py          #   用户 / 租户 / 设备模型
│   │   ├── tenant.py        #   租户模型
│   │   ├── device.py        #   设备模型（含本地 iot_device 表）
│   │   ├── device_user.py   #   设备用户关联模型
│   │   └── iot_event.py     #   IoT 事件模型（IotProcessLog / IotFlatnessData / IotAlarm / IotWebhookLog）
│   ├── routers/             # API 路由
│   │   ├── auth.py          #   认证路由（/sys/login、/sys/token/refresh、changePassword）
│   │   ├── users.py         #   用户管理路由（/sys/user/*）
│   │   ├── tenants.py       #   租户管理路由（/sys/tenant/*）
│   │   ├── devices.py       #   设备管理路由（/iot/admin/device/*，含 syncAll 主动同步）
│   │   ├── iot.py           #   IoT 数据路由（/iot/*：叶片/加工日志/平面度/统计/告警/下载；列表/详情分离、后端分页）
│   │   ├── webhook.py       #   Webhook 接收路由（/webhook/event/*：process_log/flatness_data/alarm/device_state 推送 + 告警查询）
│   │   ├── reports.py       #   报表中心路由（/iot/reports/*）
│   │   └── operation_logs.py#   操作日志路由（/sys/operationLog/*）
│   ├── schemas/             # Pydantic 请求/响应模型
│   │   └── response.py      #   统一响应格式
│   ├── services/            # 业务逻辑层
│   │   ├── auth_service.py  #   认证服务（登录验证、JWT 生成、超管初始化）
│   │   ├── user_service.py  #   用户服务
│   │   ├── tenant_service.py#   租户服务
│   │   ├── device_service.py#   设备服务（含 sync_from_jetlinks）
│   │   ├── jetlinks_service.py#  JetLinks 对接服务（仅 sync_devices / sync_products）
│   │   ├── webhook_service.py#  Webhook 落库与查询（叶片/平面度/告警聚合、分页）
│   │   ├── report_service.py #   报表统计服务
│   │   ├── operation_log_service.py# 操作日志服务
│   │   └── excel_service.py #   Excel 导出服务
│   └── utils/               # 工具函数
│       └── security.py      #   密码哈希、JWT 编解码
├── migrate_add_time_index.py        # 迁移脚本：补时间索引
├── migrate_drop_process_blade_index.py   # 迁移脚本：删 process_log 死索引
├── migrate_drop_flatness_blade_index.py  # 迁移脚本：删 flatness 死索引
├── migrate_blade_notnull.py            # 迁移脚本：blade_id 改 NOT NULL + 去重
├── init_db.sql              # 数据库初始化 SQL
├── init_admin.py            # 管理员初始化脚本
├── requirements.txt         # Python 依赖
├── start.py                 # 启动入口（uvicorn）
└── .env                     # 环境变量配置（敏感信息，不提交）
```

## 快速开始

### 环境要求

- Python 3.10+
- MySQL 8.0+

### 1. 创建数据库
### 2. 配置环境变量

复制并编辑 `.env` 文件：

```env
# 数据库配置
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=iot

# JWT 配置
JWT_SECRET=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24

# JetLinks 配置
JETLINKS_BASE_URL=http://your-jetlinks-server:8848
JETLINKS_USERNAME=admin
JETLINKS_PASSWORD=your-password
JETLINKS_PRODUCT_ID=your-product-id

# 服务配置
HOST=0.0.0.0
PORT=8080
```

### 3. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

### 4. 启动服务

```bash
python start.py
```

服务启动后：

| 地址                          | 说明             |
| --------------------------- | -------------- |
| http://localhost:8080       | API 服务         |
| http://localhost:8080/docs  | Swagger API 文档 |
| http://localhost:8080/redoc | ReDoc API 文档   |

## 数据库迁移脚本（存量环境）

平台启动时通过 `Base.metadata.create_all` 建表：**全新环境**会自动按模型创建表与索引，无需手动迁移；但对**已存在数据的存量环境**，`create_all` 不会给已存在的表补索引 / 改列属性，需运行以下脚本。

> ⚠️ 运行前请务必对数据库做完整备份！部分脚本会删除历史数据或修改表结构。

| 脚本 | 用途 | 用法 |
| --- | --- | --- |
| `migrate_add_time_index.py` | 为 `iot_process_log` / `iot_flatness_data` 补充时间索引（`event_time`、`device_id + event_time`）。全新环境无需运行；存量环境缺索引时运行。 | `python migrate_add_time_index.py --apply` |
| `migrate_drop_process_blade_index.py` | 删除 `iot_process_log` 上已失效的 `(device_id, blade_id, event_time)` 死索引。 | `python migrate_drop_process_blade_index.py --apply` |
| `migrate_drop_flatness_blade_index.py` | 删除 `iot_flatness_data` 上已失效的 `(device_id, blade_id, event_time)` 死索引。 | `python migrate_drop_flatness_blade_index.py --apply` |
| `migrate_blade_notnull.py` | 清理 `blade_id` 为 NULL 的历史行，并对两表 `blade_id` 列 ALTER 为 NOT NULL（可选配合 `--dedup` 按唯一键去重、仅保留最新一条）。 | `python migrate_blade_notnull.py --force` |

所有脚本均支持 **预检模式**：不带 `--apply` / `--force` 时仅统计并打印影响范围，**不改动数据库**，可先预检确认。脚本须在项目根目录、且已激活虚拟环境下运行（内部 `from app.database import ...`）：

```bash
cd iot_back
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 索引：先预检再执行
python migrate_add_time_index.py            # 预检：列出缺失索引
python migrate_add_time_index.py --apply    # 执行：创建缺失索引

# 死索引清理（幂等，可重复执行）
python migrate_drop_process_blade_index.py --apply
python migrate_drop_flatness_blade_index.py --apply

# blade_id 改 NOT NULL：先预检 -> 确认无碍后 --force
python migrate_blade_notnull.py             # 预检：统计 NULL 行 / 重复行
python migrate_blade_notnull.py --dedup      # 预检：额外统计重复行
python migrate_blade_notnull.py --force      # 执行：清理 NULL 行 + ALTER NOT NULL
python migrate_blade_notnull.py --dedup --force  # 执行：清理 NULL 行 + 去重 + ALTER NOT NULL
```

## API 概览

| 模块     | 路径前缀                         | 说明             |
| ------ | ---------------------------- | -------------- |
| 认证     | `/sys`                       | 登录、Token 刷新、修改密码 |
| 用户管理   | `/sys/user`                  | 用户 CRUD        |
| 租户管理   | `/sys/tenant`                | 租户 CRUD        |
| 设备管理   | `/iot/admin/device`          | 设备 CRUD、主动同步（syncAll） |
| IoT 数据 | `/iot`                       | 本地库查询（叶片/加工日志/平面度/统计/告警/下载；列表-详情分离、后端分页；`/agg` 别名、device/summary、device/status 已移除） |
| 报表中心   | `/iot/reports`               | 加工/设备/OEE/型号/告警 报表与 Excel 导出 |
| Webhook | `/webhook/event`             | 接收 JetLinks 推送（process_log / flatness_data / alarm / device_state）+ 告警查询 |
| 操作日志   | `/sys/operationLog`          | 操作日志分页查询       |

## 默认管理员

首次启动时自动创建：

- 账号名：`admin`
- 密码：`admin123`

> ⚠️ 生产环境请立即修改默认密码。

## 生产部署

```bash
# 使用多 worker 模式
uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 4

# 或使用 gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080
```
