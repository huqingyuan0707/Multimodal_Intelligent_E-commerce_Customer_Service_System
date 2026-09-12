"""认证服务（纯函数，不依赖 FastAPI 对象，对齐 AGENTS.md §3）

链路：endpoints.login 解析 → authenticate 查库验密 → issue_token 发 JWT。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import issue_token, split_roles, verify_password
from app.core.user_context import CurrentUser
from app.db.models import User


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
