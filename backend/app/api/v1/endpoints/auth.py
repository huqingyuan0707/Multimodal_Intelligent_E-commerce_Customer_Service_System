"""认证端点（真实验密发 JWT，对齐 API 规范 §4.1）

链路：POST /auth/login → auth_service.authenticate → ok({token,user})；
      POST /auth/switch → auth_service.impersonate + auth.switch 审计 → ok({token,user})；
      GET /auth/me、POST /auth/logout 走路由级 get_current_user。
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


class SwitchRequest(BaseModel):
    """代入切换入参（目标用户名，须与操作人同租户）。"""

    username: str


def _user_payload(user: CurrentUser) -> dict[str, object]:
    """用户载荷：本项目「角色即权限」（require_perm 直接查 roles），perms 与 roles 同源。

    前端顶栏/菜单用 roles，按钮级与路由守卫用 perms，两字段同值便于对齐 API 规范 §4.1。
    """
    return {
        "name": user.username,
        "tenant": user.tenant,
        "roles": user.roles,
        "perms": user.roles,
    }


@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> object:
    """验密：空账号 400(1001)，验密失败 401(1002) 中文提示；成功发 JWT。

    注：失败沿用 1002 与 HTTP 401（规范 §2），前端登录请求豁免中央 handle401，避免密码错就刷新页面。
    """
    username = payload.username.strip()
    if not username or not payload.password.strip():
        return fail(ErrorCode.PARAM_INVALID, "请输入用户名和密码", 400)
    try:
        user = await auth_service.authenticate(db, username, payload.password)
    except ValueError as exc:
        return fail(ErrorCode.UNAUTHORIZED, str(exc), 401)
    return ok({"token": auth_service.to_token(user), "user": _user_payload(user)}, "登录成功")


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
    """返回 Token 解析出的当前用户（路由级依赖已鉴权，此处显式取人）。"""
    return ok(_user_payload(user), "获取成功")


@router.post("/logout")
async def logout(_user: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
    """登出：JWT 无状态，服务端仅确认身份并留痕，登录态清理由前端完成（规范 §4.1）。"""
    return ok(None, "已退出登录")


@router.post("/switch")
async def switch(
    payload: SwitchRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """管理员免密代入同租户用户：签发目标 JWT + 记 auth.switch 审计（谁切到谁留痕）。

    注：代入资格与目标归属由 service 校验（失败转 1003/1004 中文信封）；新 token
    与 login 同结构，后续 tenant 隔离自动按目标口径生效。
    """
    target = await auth_service.switch_user(db, actor=user, username=payload.username)
    return ok(
        {"token": auth_service.to_token(target), "user": _user_payload(target)},
        f"已切换到用户{target.username}",
    )


@router.delete("/me/memory")
async def forget_my_memory(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """一键遗忘我的记忆（FR-4 GDPR/个保：长期偏好按户清 + 跨会话近况 + 线程快照全扫，审计留痕）。

    只清记忆层（本人数据，无需额外权限）；会话消息原文不动，会话级遗忘走 DELETE sessions。
    """
    from app.services import memory_service

    data = await memory_service.forget_user(db, tenant=user.tenant, username=user.username)
    return ok(data, "已清除我的跨会话记忆与长期偏好")
