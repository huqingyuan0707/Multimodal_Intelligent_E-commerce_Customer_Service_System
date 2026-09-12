"""当前用户上下文（安全红线，对齐 API 规范 §3）

链路：get_current_user 写入 → current_user()/access_context() 读取。
记忆/检索读写键必须是 (tenant, Token用户名, thread) 同一口径。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    """Token 解析后的最小用户信息，不含密钥。"""

    username: str
    tenant: str
    roles: list[str]


_current: ContextVar[CurrentUser | None] = ContextVar("current_user", default=None)


def set_current_user(user: CurrentUser | None) -> None:
    """仅由鉴权依赖调用，业务代码只读。"""
    _current.set(user)


def current_user() -> CurrentUser:
    """service 层取人唯一入口，绝不从请求体取 tenant/user。"""
    user = _current.get()
    if user is None:
        raise RuntimeError("未鉴权：缺少 get_current_user 依赖")
    return user


def access_context() -> dict[str, str]:
    """可见范围推导（租户+用户），供 RAG/记忆过滤使用。"""
    user = current_user()
    return {"tenant": user.tenant, "username": user.username}
