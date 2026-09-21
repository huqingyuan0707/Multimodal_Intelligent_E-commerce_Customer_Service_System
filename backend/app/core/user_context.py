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
#: 跨系统「代表谁」标识（office-agent 经 X-On-Behalf-Of 透传）。
#: 只由服务账号白名单主体写入；审计按 (username=调用方, on_behalf_of=发起人) 两列留痕。
_on_behalf_of: ContextVar[str] = ContextVar("on_behalf_of", default="")


def set_current_user(user: CurrentUser | None) -> None:
    """仅由鉴权依赖调用，业务代码只读。"""
    _current.set(user)


def set_on_behalf_of(value: str) -> None:
    """仅由已校验的服务账号入口调用（白名单判定在外，本函数不做信任判断）。"""
    _on_behalf_of.set((value or "").strip())


def current_on_behalf_of() -> str:
    """取本次请求的代表人（未透传时为空串，审计据此留痕）。"""
    return _on_behalf_of.get()


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
