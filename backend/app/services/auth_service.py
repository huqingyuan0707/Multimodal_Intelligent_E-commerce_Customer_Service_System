"""认证服务（纯函数，不依赖 FastAPI 对象，对齐 AGENTS.md §3）

链路：endpoints.login 解析 → authenticate 查库验密 → issue_token 发 JWT；
      endpoints.switch 解析 → impersonate 校验代入资格 → issue_token 发目标 JWT。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.core.governance import has_scope
from app.core.security import issue_token, split_roles, verify_password
from app.core.user_context import CurrentUser
from app.db.models import User
from app.services.admin_service import record_audit


async def authenticate(db: AsyncSession, username: str, password: str) -> CurrentUser:
    """验密通过返回 CurrentUser，失败抛 ValueError（端点转 401 中文提示）。"""
    row = (
        await db.execute(select(User).where(User.username == username.strip()))
    ).scalar_one_or_none()
    if row is None or not verify_password(password, row.pwd_hash):
        raise ValueError("用户名或密码错误")
    return CurrentUser(username=row.username, tenant=row.tenant, roles=split_roles(row.roles))


def to_token(user: CurrentUser) -> str:
    """CurrentUser 签发为 JWT。"""
    return issue_token(user.username, user.tenant, user.roles)


async def impersonate(db: AsyncSession, *, actor: CurrentUser, username: str) -> CurrentUser:
    """管理员免密代入同租户用户（顶栏“切换用户”，免去退出重登）。

    口径：actor 须 admin Scope（`has_scope` 与 require_perm 同源）；目标须与 actor
    同租户且存在，否则 404 不泄露跨租户存在性。失败抛 BusinessError（端点不 try）。
    """
    target = (username or "").strip()
    if not target:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择要切换的用户")
    if not has_scope(actor.roles, "admin"):
        raise BusinessError(ErrorCode.FORBIDDEN, "仅管理员可切换用户", 403)
    row = (
        await db.execute(select(User).where(User.tenant == actor.tenant, User.username == target))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "目标用户不存在或无权访问", 404)
    return CurrentUser(username=row.username, tenant=row.tenant, roles=split_roles(row.roles))


async def switch_user(db: AsyncSession, *, actor: CurrentUser, username: str) -> CurrentUser:
    """代入切换事务：impersonate 校验 → 记 auth.switch 审计 → 同事务提交。

    事务收口在 service 层（endpoint 禁止直写 db.commit，防屎山门禁硬拦）。
    """
    target = await impersonate(db, actor=actor, username=username)
    await record_audit(
        db,
        tenant=actor.tenant,
        actor=actor.username,
        action="auth.switch",
        target=target.username,
        detail={"from": actor.username, "to": target.username},
    )
    await db.commit()
    return target
