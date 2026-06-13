from .auth import router as auth_router
from .users import router as users_router
from .tenants import router as tenants_router
from .devices import router as devices_router
from .iot import router as iot_router

__all__ = ["auth_router", "users_router", "tenants_router", "devices_router", "iot_router"]
