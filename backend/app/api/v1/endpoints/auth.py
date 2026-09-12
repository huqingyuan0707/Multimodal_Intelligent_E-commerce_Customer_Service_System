"""认证端点（真实验密发 JWT，对齐 API 规范 §4.1）

链路：POST /auth/login → auth_service.authenticate → ok({token, user})。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode
from app.core.rbac import get_current_user
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录请求体（端点私有 DTO 可放本文件）。"""

    username: str
    password: str


@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> object:
    """验密：通过发 JWT，失败 401 中文提示（前端 handle401 只处理 1002/HTTP401）。"""
    try:
        user = await auth_service.authenticate(db, payload.username, payload.password)
    except ValueError as exc:
        return fail(ErrorCode.UNAUTHORIZED, str(exc), 401)
    return ok(
        {
            "token": auth_service.to_token(user),
            "user": {"name": user.username, "tenant": user.tenant, "roles": user.roles},
        },
        "登录成功",
    )


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
    """返回 Token 解析出的当前用户（路由级依赖已鉴权，此处显式取人）。"""
    return ok(
        {"name": user.username, "tenant": user.tenant, "roles": user.roles},
        "获取成功",
    )
