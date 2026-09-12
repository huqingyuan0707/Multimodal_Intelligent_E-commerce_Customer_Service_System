"""认证鉴权依赖（路由级登录 + 敏感鉴权，对齐 API 规范 §3）

链路：OAuth2 Bearer → 解析 Token → 写入 ContextVar → 业务用 current_user()。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_token
from app.core.user_context import CurrentUser, set_current_user

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """登录依赖：验签解 JWT → 写入 ContextVar → 业务经 current_user() 取人。"""
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        claims = decode_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    roles = claims.get("roles")
    user = CurrentUser(
        username=str(claims.get("sub", "")),
        tenant=str(claims.get("tenant", "")),
        roles=list(roles) if isinstance(roles, list) else [],
    )
    if not user.username or not user.tenant:
        raise HTTPException(status_code=401, detail="Token 非法")
    set_current_user(user)
    return user


def require_perm(perm: str) -> Callable[..., Awaitable[CurrentUser]]:
    """敏感端点二次鉴权，如 Depends(require_perm("kb"))。"""

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if perm not in user.roles and "*" not in user.roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return _check
