"""操作日志服务"""
from datetime import datetime, timedelta
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.operation_log import SysOperationLog


async def create_log(
    db: AsyncSession,
    account: str,
    operation_type: str,
    detail: str = "",
    ip_address: str | None = None,
) -> None:
    """写入操作日志"""
    log = SysOperationLog(
        account=account,
        operation_type=operation_type,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(log)
    await db.commit()


async def get_log_list(
    db: AsyncSession,
    page_no: int = 1,
    page_size: int = 20,
    account: str | None = None,
    operation_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    """分页查询操作日志"""
    stmt = select(SysOperationLog)

    if account:
        stmt = stmt.where(SysOperationLog.account.like(f"%{account}%"))
    if operation_type:
        stmt = stmt.where(SysOperationLog.operation_type == operation_type)
    if start_time:
        try:
            st = datetime.fromisoformat(start_time)
            stmt = stmt.where(SysOperationLog.operate_time >= st)
        except ValueError:
            pass
    if end_time:
        try:
            et = datetime.fromisoformat(end_time)
            et = et + timedelta(days=1)
            stmt = stmt.where(SysOperationLog.operate_time < et)
        except ValueError:
            pass

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(desc(SysOperationLog.operate_time))
    offset = (page_no - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        "records": [
            {
                "id": r.id,
                "operateTime": r.operate_time.isoformat() if r.operate_time else None,
                "account": r.account,
                "operationType": r.operation_type,
                "detail": r.detail,
                "ipAddress": r.ip_address,
            }
            for r in records
        ],
        "total": total,
    }
