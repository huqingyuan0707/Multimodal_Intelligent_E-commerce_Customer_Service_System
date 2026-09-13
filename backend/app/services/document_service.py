"""知识库文档服务（前置地基：真实落库，对齐 API 规范 §4.4 + 数据模型文档 §2）

链路：endpoints/documents 薄封装 → 本模块 → kb_docs 表（sha256 租户内去重）。
红线：所有查询强制按 tenant 过滤；上传去重返回 skipped=True（中文提示由端点组装）。
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import KbDoc


def _dt_text(value: Any) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def doc_to_dict(row: KbDoc) -> dict[str, Any]:
    return {
        "id": row.id,
        "doc_id": row.id,
        "title": row.title,
        "security_level": row.security_level,
        "sha256": row.sha256,
        "version": row.version,
        "created_at": _dt_text(row.created_at),
    }


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def list_docs(
    db: AsyncSession, *, tenant: str, page: int = 1, size: int = 20
) -> list[dict[str, Any]]:
    """文档列表（租户隔离倒序；page/size 默认 20，暂返回数组保持前端兼容）。"""
    stmt = (
        select(KbDoc)
        .where(KbDoc.tenant == tenant)
        .order_by(KbDoc.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = list((await db.execute(stmt)).scalars())
    return [doc_to_dict(r) for r in rows]


async def count_docs(db: AsyncSession, *, tenant: str) -> int:
    total = (
        await db.execute(select(func.count()).select_from(KbDoc).where(KbDoc.tenant == tenant))
    ).scalar_one()
    return int(total)


async def get_or_create_doc(
    db: AsyncSession, *, tenant: str, title: str, content: str, raw: bytes
) -> tuple[KbDoc, bool]:
    """按 sha256 去重入库：已存在返回 (旧行, True)，新建返回 (新行, False)。"""
    digest = sha256_of(raw)
    existed = (
        await db.execute(select(KbDoc).where(KbDoc.tenant == tenant, KbDoc.sha256 == digest))
    ).scalar_one_or_none()
    if existed is not None:
        return existed, True
    if not (title or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请至少选择一个文件")
    row = KbDoc(
        tenant=tenant,
        title=title.strip()[:200],
        content=content,
        sha256=digest,
        version=1,
    )
    db.add(row)
    await db.commit()
    return row, False


async def delete_doc(db: AsyncSession, *, tenant: str, doc_id: str) -> None:
    """删除文档（跨租户 404；分块级联由外键处理）。"""
    row = (
        await db.execute(select(KbDoc).where(KbDoc.id == doc_id, KbDoc.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "文档不存在或无权访问", 404)
    await db.delete(row)
    await db.commit()
