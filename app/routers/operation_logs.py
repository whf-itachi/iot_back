"""操作日志查询路由"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..schemas.response import Result
from ..services import operation_log_service
from ..utils.security import require_admin

router = APIRouter(tags=["操作日志"])


@router.get("/sys/operationLog/list")
async def list_operation_logs(
    pageNo: int = Query(1, alias="pageNo"),
    pageSize: int = Query(20, alias="pageSize"),
    account: str | None = Query(None, alias="account"),
    operationType: str | None = Query(None, alias="operationType"),
    startTime: str | None = Query(None, alias="startTime"),
    endTime: str | None = Query(None, alias="endTime"),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """查询操作日志（仅管理员可访问）"""
    try:
        data = await operation_log_service.get_log_list(
            db, pageNo, pageSize, account, operationType, startTime, endTime
        )
        return Result.ok(data, "查询成功")
    except Exception as e:
        return Result.error(str(e))


@router.get("/sys/operationLog/types")
async def get_operation_types(
    _admin: dict = Depends(require_admin),
):
    """获取所有操作类型列表"""
    types = [
        "新增用户", "编辑用户", "删除用户", "管理员重置密码", "用户修改密码",
        "新增租户", "编辑租户", "删除租户",
        "设备绑定用户", "设备解绑用户", "清理用户设备绑定",
        "用户分配租户", "设备分配租户",
        "保存用户扩展信息", "删除用户扩展信息",
    ]
    return Result.ok(types)
