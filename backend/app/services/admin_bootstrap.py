"""生产首个管理员创建与口令轮换（对齐 API 规范 §4.1 认证 + 数据模型 §6 种子节）

链路：scripts/create_admin.py（参数解析）→ ensure_admin()（幂等落库）→ users 表。
种子账号（SEED_*）仅限本地演示；生产关种子后，首个管理员一律走本模块创建，不经过演示通道。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import is_default_seed_password, settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.security import hash_password, split_roles
from app.db.models import User

MIN_PASSWORD_LEN = 8


async def ensure_admin(
    db: AsyncSession,
    *,
    tenant: str,
    username: str,
    password: str,
    roles: str = "admin",
    reset: bool = False,
) -> str:
    """幂等建管理员：不存在则建（"created"）；已存在且 reset=False 则不动（"exists"）。

    已存在且 reset=True 时重设密码与并集补齐角色（"reset"，供口令泄漏轮换）。
    弱口令与本地演示默认口令直接 1001 拒绝，禁止把演示口令带上生产。
    """
    clean_tenant = (tenant or "").strip()
    clean_name = (username or "").strip()
    if not clean_tenant or not clean_name:
        raise BusinessError(ErrorCode.PARAM_INVALID, "租户与用户名不能为空", 400)
    if len(password) < MIN_PASSWORD_LEN:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"密码至少 {MIN_PASSWORD_LEN} 位", 400)
    if is_default_seed_password(password):
        raise BusinessError(ErrorCode.PARAM_INVALID, "禁止使用本地演示默认口令，请换强口令", 400)
    wanted = split_roles(roles)
    if not wanted:
        raise BusinessError(ErrorCode.PARAM_INVALID, "角色不能为空（如 admin）", 400)

    row = (
        await db.execute(
            select(User).where(User.tenant == clean_tenant, User.username == clean_name)
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            User(
                tenant=clean_tenant,
                username=clean_name,
                pwd_hash=hash_password(password),
                roles=settings.ROLES_SEPARATOR.join(wanted),
            )
        )
        await db.commit()
        return "created"
    if not reset:
        return "exists"
    row.pwd_hash = hash_password(password)
    have = split_roles(row.roles)
    missing = [r for r in wanted if r not in have]
    if missing:
        row.roles = settings.ROLES_SEPARATOR.join([*have, *missing])
    await db.commit()
    return "reset"
