"""租户隔离与权限网关（前置地基，对齐 API 规范 §3 + 数据模型文档 §2）

链路：get_current_user 写入 ContextVar → governance.access_context() 推导可见范围
→ services 所有查询强制按 tenant 过滤；敏感端点再叠 require_perm/require_any_perm。
绝不信任请求体 tenant_id/user_id；记忆/检索键 (tenant, Token用户名, thread) 同一口径。
"""

from __future__ import annotations

from app.core.user_context import access_context, current_user

__all__ = ["access_context", "current_user", "has_scope", "tenant_of"]


def tenant_of() -> str:
    """当前租户（services 过滤唯一入口，避免各处拼 user.tenant）。"""
    return current_user().tenant


def has_scope(user_roles: list[str], *wanted: str) -> bool:
    """Scope 校验：角色即权限口径，命中任一即放行，`*` 通配（与 rbac 同源）。"""
    if "*" in user_roles:
        return True
    return any(w in user_roles for w in wanted)
