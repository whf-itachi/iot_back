"""FastAPI 主应用 — IoT 叶片加工监控平台后端"""
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import engine, Base
from .routers import auth_router, users_router, tenants_router, devices_router, iot_router, webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表 + 初始化超管"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        from .database import async_session
        from .services.auth_service import ensure_admin_user
        async with async_session() as db:
            await ensure_admin_user(db)

        print("[iot_back] 数据库连接成功，admin 用户已就绪")
    except Exception as e:
        print(f"[iot_back] ⚠ 数据库连接失败: {e}", file=sys.stderr)
        print(f"[iot_back] 请检查 .env 中的数据库配置 (DB_HOST/DB_USER/DB_PASSWORD/DB_NAME)", file=sys.stderr)
        print(f"[iot_back] 服务将以受限模式启动（API 文档可访问，数据库功能不可用）", file=sys.stderr)

    yield
    await engine.dispose()


app = FastAPI(
    title="IoT 叶片加工监控平台",
    description="FastAPI 后端 — IoT 叶片加工监控平台",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(tenants_router)
app.include_router(devices_router)
app.include_router(iot_router)
app.include_router(webhook_router)


@app.get("/")
async def root():
    return {"service": "IoT 叶片加工监控平台", "version": "2.0.0", "status": "running"}
