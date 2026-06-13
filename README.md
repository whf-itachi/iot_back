# IoT Backend — 叶片加工监控平台后端

基于 **FastAPI** 的 IoT 叶片加工监控系统后端，提供用户认证、设备管理、租户管理、JetLinks 对接等 API 服务。

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.115 | Web 框架 |
| Uvicorn | 0.34 | ASGI 服务器 |
| SQLAlchemy | 2.0 | ORM（异步模式） |
| aiomysql | 0.2 | MySQL 异步驱动 |
| Pydantic | 2.10 | 数据校验 & 配置管理 |
| python-jose | 3.3 | JWT 令牌处理 |
| passlib | 1.7 | 密码哈希 |
| httpx | 0.28 | HTTP 客户端（对接 JetLinks） |
| Alembic | 1.14 | 数据库迁移 |

## 项目结构

```
iot_back/
├── app/
│   ├── main.py              # FastAPI 应用入口（CORS、路由注册、生命周期）
│   ├── config.py            # 配置管理（pydantic-settings，从 .env 读取）
│   ├── database.py          # 数据库连接（SQLAlchemy 异步引擎 + session）
│   ├── models/              # ORM 模型
│   │   ├── user.py          #   用户模型
│   │   ├── tenant.py        #   租户模型
│   │   ├── device.py        #   设备模型
│   │   └── device_user.py   #   设备用户关联模型
│   ├── routers/             # API 路由
│   │   ├── auth.py          #   认证路由（登录/登出/token刷新）
│   │   ├── users.py         #   用户管理路由
│   │   ├── tenants.py       #   租户管理路由
│   │   ├── devices.py       #   设备管理路由
│   │   └── iot.py           #   IoT 数据路由（对接 JetLinks）
│   ├── schemas/             # Pydantic 请求/响应模型
│   │   └── response.py      #   统一响应格式
│   ├── services/            # 业务逻辑层
│   │   ├── auth_service.py  #   认证服务（登录验证、JWT 生成、超管初始化）
│   │   ├── user_service.py  #   用户服务
│   │   ├── tenant_service.py#   租户服务
│   │   ├── device_service.py#   设备服务
│   │   └── jetlinks_service.py#  JetLinks 对接服务
│   └── utils/               # 工具函数
│       └── security.py      #   密码哈希、JWT 编解码
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

```bash
mysql -u root -p < init_db.sql
```

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

| 地址 | 说明 |
|------|------|
| http://localhost:8080 | API 服务 |
| http://localhost:8080/docs | Swagger API 文档 |
| http://localhost:8080/redoc | ReDoc API 文档 |

## API 概览

| 模块 | 路径前缀 | 说明 |
|------|----------|------|
| 认证 | `/api/auth` | 登录、登出、Token 刷新 |
| 用户管理 | `/api/users` | 用户 CRUD |
| 租户管理 | `/api/tenants` | 租户 CRUD |
| 设备管理 | `/api/devices` | 设备 CRUD、数据查询 |
| IoT 数据 | `/api/iot` | JetLinks 数据代理 |

## 默认管理员

首次启动时自动创建：

- 用户名：`admin`
- 密码：`admin123`

> ⚠️ 生产环境请立即修改默认密码。

## 生产部署

```bash
# 使用多 worker 模式
uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 4

# 或使用 gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080
```
