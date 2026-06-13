"""统一响应模型"""
from typing import Any, Optional
from pydantic import BaseModel


class Result(BaseModel):
    success: bool = True
    code: int = 200
    message: str = "操作成功"
    result: Any = None

    @classmethod
    def ok(cls, data: Any = None, msg: str = "操作成功") -> "Result":
        return cls(success=True, code=200, message=msg, result=data)

    @classmethod
    def error(cls, msg: str = "操作失败", code: int = 500) -> "Result":
        return cls(success=False, code=code, message=msg, result=None)


class PageResult(BaseModel):
    records: list = []
    total: int = 0
    size: int = 20
    current: int = 1
    pages: int = 0
