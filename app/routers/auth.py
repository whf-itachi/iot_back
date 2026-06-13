"""认证路由 — /api/sys/login, /api/sys/user/changePassword"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from ..database import get_db
from ..schemas.response import Result
from ..services import auth_service

router = APIRouter(tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePwdRequest(BaseModel):
    username: str
    password: str      # 原密码
    newpassword: str    # 新密码


@router.post("/sys/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = await auth_service.login(db, req.username, req.password)
        return Result.ok(data, "登录成功")
    except ValueError as e:
        return Result.error(str(e))


@router.put("/sys/user/changePassword")
async def change_password(req: ChangePwdRequest, db: AsyncSession = Depends(get_db)):
    try:
        await auth_service.change_password(db, req.username, req.password, req.newpassword)
        return Result.ok(None, "密码修改成功")
    except ValueError as e:
        return Result.error(str(e))
