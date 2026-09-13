"""管理后台服务（租户/配额/审计框架，对齐 FRD FR-8 + 数据模型 §2）

链路：endpoints/admin → 本模块 → tenants/users/audit_logs。
红线：绝不信任请求体 tenant 做权限判断，操作人一律调用方显式传 actor（端点从 Token 取）；
      审计只追加不改，租户/配额/角色变更必须同步记一条。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import AuditLog, Tenant, User

TENANT_STATUSES = ("active", "suspended", "disabled")
TENANT_STATUS_LABELS = {"active": "正常", "suspended": "欠费停服", "disabled": "禁用"}
TENANT_PLAN_LABELS = {"trial": "试用", "basic": "基础版", "pro": "专业版", "enterprise": "旗舰版"}


def _dt_text(value) -> str:
    """时间统一口径：空格秒（与商品/订单/审批一致）。"""
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        loaded = json.loads(text or "")
    except json.JSONDecodeError:
        return fallback
    return loaded


def tenant_to_dict(row: Tenant) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "plan": row.plan,
        "plan_label": TENANT_PLAN_LABELS.get(row.plan, row.plan),
        "status": row.status,
        "status_label": TENANT_STATUS_LABELS.get(row.status, row.status),
        "quota_tokens": row.quota_tokens,
        "quota_concurrency": row.quota_concurrency,
        "note": row.note,
        "created_at": _dt_text(row.created_at),
    }


def audit_to_dict(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant": row.tenant,
        "actor": row.actor,
        "action": row.action,
        "target": row.target,
        "detail": _parse_json(row.detail, {}),
        "created_at": _dt_text(row.created_at),
    }


def user_to_dict(row: User) -> dict[str, Any]:
    from app.core.security import split_roles

    roles = split_roles(row.roles or "")
    return {
        "id": row.id,
        "tenant": row.tenant,
        "username": row.username,
        "roles": roles,
        "created_at": _dt_text(row.created_at),
    }


async def record_audit(
    db: AsyncSession,
    *,
    tenant: str,
    actor: str,
    action: str,
    target: str = "",
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """记一条审计（只 flush 不 commit，与业务写入同事务）。"""
    row = AuditLog(
        tenant=tenant or "",
        actor=actor or "",
        action=action,
        target=target or "",
        detail=json.dumps(detail or {}, ensure_ascii=False),
    )
    db.add(row)
    await db.flush()
    return row


def _check_code(code: str) -> str:
    cleaned = (code or "").strip()
    if not cleaned or len(cleaned) > 64 or any(ch.isspace() for ch in cleaned):
        raise BusinessError(ErrorCode.PARAM_INVALID, "租户编码不能为空且不能含空格（≤64 字符）")
    return cleaned


async def get_tenant_or_raise(db: AsyncSession, code: str) -> Tenant:
    row = (await db.execute(select(Tenant).where(Tenant.code == code))).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "租户不存在", 404)
    return row


async def list_tenants(
    db: AsyncSession,
    *,
    keyword: str = "",
    plan: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """租户分页（全局视角，仅 admin 可调；keyword 匹配 code/name）。"""
    if plan and plan not in settings.TENANT_PLANS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"套餐非法：{plan}")
    if status and status not in TENANT_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"租户状态非法：{status}")
    stmt = select(Tenant)
    if plan:
        stmt = stmt.where(Tenant.plan == plan)
    if status:
        stmt = stmt.where(Tenant.status == status)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Tenant.code.like(like), Tenant.name.like(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(Tenant.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [tenant_to_dict(r) for r in rows],
    }


async def create_tenant(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    plan: str = "trial",
    quota_tokens: int | None = None,
    quota_concurrency: int | None = None,
    actor: str = "",
) -> Tenant:
    """新建租户（编码全局唯一；配额缺省走 Settings 默认）。"""
    cleaned = _check_code(code)
    if not (name or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "租户名称不能为空")
    if plan not in settings.TENANT_PLANS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"套餐非法：{plan}")
    existed = (await db.execute(select(Tenant).where(Tenant.code == cleaned))).scalar_one_or_none()
    if existed is not None:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"租户编码已存在：{cleaned}")
    row = Tenant(
        code=cleaned,
        name=name.strip(),
        plan=plan,
        quota_tokens=quota_tokens if quota_tokens is not None else settings.DEFAULT_QUOTA_TOKENS,
        quota_concurrency=(
            quota_concurrency
            if quota_concurrency is not None
            else settings.DEFAULT_QUOTA_CONCURRENCY
        ),
    )
    if row.quota_tokens <= 0 or row.quota_concurrency <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "配额必须为正数")
    db.add(row)
    await db.flush()
    await record_audit(
        db,
        tenant=cleaned,
        actor=actor,
        action="tenant.create",
        target=cleaned,
        detail={"plan": plan},
    )
    await db.commit()
    return row


async def update_quota(
    db: AsyncSession,
    *,
    code: str,
    quota_tokens: int,
    quota_concurrency: int,
    actor: str = "",
) -> Tenant:
    """改配额（危险操作，前端双重 confirm；同步记审计供回溯）。"""
    if quota_tokens <= 0 or quota_concurrency <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "配额必须为正数")
    row = await get_tenant_or_raise(db, code)
    old = {"quota_tokens": row.quota_tokens, "quota_concurrency": row.quota_concurrency}
    row.quota_tokens = quota_tokens
    row.quota_concurrency = quota_concurrency
    await db.flush()
    await record_audit(
        db,
        tenant=code,
        actor=actor,
        action="tenant.quota",
        target=code,
        detail={**old, "quota_tokens": quota_tokens, "quota_concurrency": quota_concurrency},
    )
    await db.commit()
    return row


async def set_status(
    db: AsyncSession,
    *,
    code: str,
    status: str,
    actor: str = "",
) -> Tenant:
    """停服/恢复（欠费停服即 suspended；同步记审计）。"""
    if status not in TENANT_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"租户状态非法：{status}")
    row = await get_tenant_or_raise(db, code)
    old_status = row.status
    row.status = status
    await db.flush()
    await record_audit(
        db,
        tenant=code,
        actor=actor,
        action="tenant.status",
        target=code,
        detail={"from": old_status, "to": status},
    )
    await db.commit()
    return row


async def list_users(
    db: AsyncSession,
    *,
    tenant: str = "",
    keyword: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """用户分页（全局视角；tenant 传空=全部，keyword 匹配用户名）。"""
    stmt = select(User)
    if tenant.strip():
        stmt = stmt.where(User.tenant == tenant.strip())
    if keyword.strip():
        stmt = stmt.where(User.username.like(f"%{keyword.strip()}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(User.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [user_to_dict(r) for r in rows],
    }


async def update_user_roles(
    db: AsyncSession,
    *,
    user_id: str,
    roles: str,
    actor: str = "",
) -> User:
    """改用户角色（角色即权限口径；同步记审计）。"""
    from app.core.security import split_roles

    wanted = split_roles(roles or "")
    if not wanted:
        raise BusinessError(ErrorCode.PARAM_INVALID, "角色不能为空")
    row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "用户不存在", 404)
    old_roles = row.roles
    row.roles = settings.ROLES_SEPARATOR.join(wanted)
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="user.roles",
        target=row.username,
        detail={"from": old_roles, "to": row.roles},
    )
    await db.commit()
    return row


async def list_audits(
    db: AsyncSession,
    *,
    tenant: str = "",
    action: str = "",
    keyword: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """审计分页（只读；倒序；keyword 匹配 actor/target）。"""
    stmt = select(AuditLog)
    if tenant.strip():
        stmt = stmt.where(AuditLog.tenant == tenant.strip())
    if action.strip():
        stmt = stmt.where(AuditLog.action == action.strip())
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(AuditLog.actor.like(like), AuditLog.target.like(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [audit_to_dict(r) for r in rows],
    }


async def overview(db: AsyncSession) -> dict[str, Any]:
    """管理概览（租户数/用户数/停服数/审计数，供 Admin 顶部指标卡）。"""
    tenant_total = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    user_total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    suspended = (
        await db.execute(select(func.count()).select_from(Tenant).where(Tenant.status != "active"))
    ).scalar_one()
    audit_total = (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    return {
        "tenant_total": int(tenant_total),
        "user_total": int(user_total),
        "suspended": int(suspended),
        "audit_total": int(audit_total),
    }
