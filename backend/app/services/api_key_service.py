"""API 密钥服务（FR-8 密钥管理，对齐页面设计 §3.8「密钥（只显掩码）」）

链路：endpoints/admin 密钥端点 → 本模块 → api_keys 表（租户隔离）+ audit_logs（审计）。
红线：
- 明文只在 create_key / rotate_key 的返回值里出现一次；列表与详情一律只回掩码
  （key_to_dict 结构上就不含明文与摘要，避免将来有人「顺手」透出）。
- 库内只存 sha256 摘要，轮换即覆盖摘要：旧口令当场失效，不留「新旧双活」窗口。
- 审计只追加：创建/轮换/状态变更各记一条，detail 只落掩码，绝不落明文。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import ApiKey
from app.db.models_admin import API_KEY_STATUSES
from app.services.admin_service import dt_text, record_audit

API_KEY_STATUS_LABELS = {"active": "启用", "disabled": "已禁用"}


def _hash(plain: str) -> str:
    """摘要口径：sha256 hex（不可逆，库内唯一约束防重放摘要）。"""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _new_plain() -> str:
    """生成明文：`<prefix>_<urlsafe token>`（token 长度走 Settings，禁硬编码）。"""
    return f"{settings.API_KEY_PREFIX}_{secrets.token_urlsafe(int(settings.API_KEY_BYTES))}"


def _mask(plain: str) -> str:
    """掩码口径：`sk_live_ab12********ef34`（保留正文首尾各 MASK_KEEP 位）。"""
    head = f"{settings.API_KEY_PREFIX}_"
    body = plain[len(head) :] if plain.startswith(head) else plain
    keep = max(1, int(settings.API_KEY_MASK_KEEP))
    if len(body) <= keep * 2:
        return f"{settings.API_KEY_PREFIX}_{'*' * 12}"
    return f"{settings.API_KEY_PREFIX}_{body[:keep]}{'*' * 8}{body[-keep:]}"


def split_scopes(raw: str) -> list[str]:
    """scope 文本解析（逗号分隔，与 ROLES_SEPARATOR 无关：scope 是 API 面不是角色面）。"""
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def key_to_dict(row: ApiKey) -> dict[str, Any]:
    """密钥出参：**结构上不含明文与摘要**，只有掩码（列表页唯一可见口径）。"""
    return {
        "id": row.id,
        "tenant": row.tenant,
        "name": row.name,
        "prefix": row.prefix,
        "masked": row.masked,
        "scopes": split_scopes(row.scopes),
        "status": row.status,
        "status_label": API_KEY_STATUS_LABELS.get(row.status, row.status),
        "expired": bool(row.expires_at and row.expires_at < datetime.now()),
        "last_used_at": dt_text(row.last_used_at),
        "expires_at": dt_text(row.expires_at),
        "rotated_at": dt_text(row.rotated_at),
        "created_at": dt_text(row.created_at),
    }


async def get_key_or_raise(db: AsyncSession, key_id: str) -> ApiKey:
    row = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "密钥不存在", 404)
    return row


async def list_keys(
    db: AsyncSession,
    *,
    tenant: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """密钥分页（admin 全局视角；tenant 传空=全部；只回掩码）。"""
    if status and status not in API_KEY_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"密钥状态非法：{status}")
    stmt = select(ApiKey)
    if tenant.strip():
        stmt = stmt.where(ApiKey.tenant == tenant.strip())
    if status:
        stmt = stmt.where(ApiKey.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(ApiKey.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [key_to_dict(row) for row in rows],
    }


def parse_expires_at(text: str) -> datetime | None:
    """解析到期时间入参（`YYYY-MM-DD` 或 `YYYY-MM-DD HH:mm:ss`；空串=永不过期）。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    raise BusinessError(
        ErrorCode.PARAM_INVALID, "到期时间格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:mm:ss"
    )


async def create_key(
    db: AsyncSession,
    *,
    tenant: str,
    name: str,
    scopes: str = "",
    expires_at: datetime | None = None,
    actor: str = "",
) -> tuple[ApiKey, str]:
    """建密钥 → (行, 明文)。明文只在此刻可见一次，调用方必须原样透给前端并提示「仅显示一次」。"""
    cleaned_tenant = (tenant or "").strip()
    cleaned = (name or "").strip()
    if not cleaned_tenant:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择密钥所属租户")
    if not cleaned or len(cleaned) > 80:
        raise BusinessError(ErrorCode.PARAM_INVALID, "密钥用途名不能为空且不超过 80 字符")
    existed = (
        await db.execute(
            select(ApiKey).where(ApiKey.tenant == cleaned_tenant, ApiKey.name == cleaned)
        )
    ).scalar_one_or_none()
    if existed is not None:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"该租户下已存在同名密钥：{cleaned}")
    plain = _new_plain()
    row = ApiKey(
        tenant=cleaned_tenant,
        name=cleaned,
        prefix=settings.API_KEY_PREFIX,
        masked=_mask(plain),
        key_hash=_hash(plain),
        scopes=(scopes or settings.API_KEY_SCOPES_DEFAULT).strip(),
        status="active",
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    await record_audit(
        db,
        tenant=cleaned_tenant,
        actor=actor,
        action="apikey.create",
        target=cleaned,
        detail={"masked": row.masked, "scopes": row.scopes},
    )
    await db.commit()
    return row, plain


async def rotate_key(db: AsyncSession, *, key_id: str, actor: str = "") -> tuple[ApiKey, str]:
    """轮换 → (行, 新明文)。覆盖摘要即旧口令失效；顺带把禁用态复位为启用（前端已双重确认）。"""
    row = await get_key_or_raise(db, key_id)
    plain = _new_plain()
    old_masked = row.masked
    row.masked = _mask(plain)
    row.key_hash = _hash(plain)
    row.rotated_at = datetime.now()
    row.status = "active"
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="apikey.rotate",
        target=row.name,
        detail={"from": old_masked, "to": row.masked},
    )
    await db.commit()
    return row, plain


async def set_status(db: AsyncSession, *, key_id: str, status: str, actor: str = "") -> ApiKey:
    """启用/禁用（禁用后该口令不再可用；不删行以便审计回溯）。"""
    if status not in API_KEY_STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"密钥状态非法：{status}")
    row = await get_key_or_raise(db, key_id)
    old_status = row.status
    row.status = status
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="apikey.status",
        target=row.name,
        detail={"from": old_status, "to": status},
    )
    await db.commit()
    return row
