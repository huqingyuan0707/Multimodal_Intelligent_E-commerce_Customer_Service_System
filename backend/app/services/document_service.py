"""知识库文档服务（CRUD 编排，对齐 API 规范 §4.4 + RAG 规范 §1）

链路：endpoints/documents 薄封装 → 本模块 CRUD（列表/去重建/上传编排/
      删除/编辑）→ 解析切分下沉 document_parse，版本/流转/统计下沉
      document_lifecycle；本模块只做编排 + 薄转发（调用方导入口径不变）。
红线：查询强制按 tenant 过滤；去重返 skipped=True 中文提示由端点组装。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import KbChunk, KbDoc
from app.services import rag_governance, vector_store
from app.services.document_lifecycle import (
    _snapshot_version,
    doc_stats,
    get_doc,
    list_versions,
    rollback_doc,
    transition_doc,
)
from app.services.document_parse import (
    _channels_of,
    _dt_text,
    _parse_channels,
    _parse_date,
    _write_chunks,
    parse_seed_markdown,
    rebuild_chunks,
    run_reindex,
    sha256_of,
    split_chunks,
)
from app.services.knowledge_service import bump_corpus

# 密级三档（RAG 规范 §3：confidential 需 kb 权限；会话侧默认只召回 public）
LEVELS = ("public", "internal", "confidential")

# 生命周期（FR-13.2）：上传/种子默认 published（存量兼容）；运营新建走状态机
STATUSES = ("draft", "review", "published", "archived")

# 薄转发：解析/分块/版本/流转已下沉子模块，种子/测试/任务旧导入口径不变。
__all__ = [
    "LEVELS",
    "STATUSES",
    "count_docs",
    "delete_doc",
    "detail_to_dict",
    "doc_stats",
    "doc_to_dict",
    "get_doc",
    "get_or_create_doc",
    "ingest_upload",
    "list_docs",
    "list_versions",
    "parse_seed_markdown",
    "rebuild_chunks",
    "rollback_doc",
    "run_reindex",
    "sha256_of",
    "split_chunks",
    "transition_doc",
    "update_doc",
]


def doc_to_dict(row: KbDoc) -> dict[str, Any]:
    return {
        "id": row.id,
        "doc_id": row.id,
        "title": row.title,
        "topic": row.topic or "",
        "status": row.status or "published",
        "security_level": row.security_level,
        "channels": _channels_of(row),
        "valid_from": _dt_text(row.valid_from),
        "valid_to": _dt_text(row.valid_to),
        "sha256": row.sha256,
        "version": row.version,
        "created_at": _dt_text(row.created_at),
    }


def detail_to_dict(row: KbDoc) -> dict[str, Any]:
    """详情（含正文；列表不带 content 保持轻量）。"""
    data = doc_to_dict(row)
    data["content"] = row.content
    return data


async def list_docs(
    db: AsyncSession, *, tenant: str, page: int = 1, size: int = 20, keyword: str = ""
) -> list[dict[str, Any]]:
    """文档列表（租户隔离倒序；标题模糊筛选；page/size 默认 20；端点包成分页对象）。"""
    stmt = select(KbDoc).where(KbDoc.tenant == tenant)
    if keyword.strip():
        stmt = stmt.where(KbDoc.title.like(f"%{keyword.strip()}%"))
    stmt = stmt.order_by(KbDoc.created_at.desc()).offset((page - 1) * size).limit(size)
    rows = list((await db.execute(stmt)).scalars())
    return [doc_to_dict(r) for r in rows]


async def count_docs(db: AsyncSession, *, tenant: str, keyword: str = "") -> int:
    stmt = select(func.count()).select_from(KbDoc).where(KbDoc.tenant == tenant)
    if keyword.strip():
        stmt = stmt.where(KbDoc.title.like(f"%{keyword.strip()}%"))
    total = (await db.execute(stmt)).scalar_one()
    return int(total)


async def get_or_create_doc(
    db: AsyncSession,
    *,
    tenant: str,
    title: str,
    content: str,
    raw: bytes,
    actor: str = "",
    security_level: str = "internal",
    channels: list[str] | None = None,
    valid_from: str = "",
    valid_to: str = "",
    topic: str = "",
    status: str = "published",
) -> tuple[KbDoc, bool]:
    """按 sha256 去重入库：已存在返 (旧行, True)，新建返 (新行, False)。

    13 步口径：切分→向量化双写；写操作记 audit；元数据只在新建落库。
    status 默认 published（存量/种子兼容）；运营上传传 draft 走审核流。
    """
    digest = sha256_of(raw)
    existed = (
        await db.execute(select(KbDoc).where(KbDoc.tenant == tenant, KbDoc.sha256 == digest))
    ).scalar_one_or_none()
    if existed is not None:
        rag_governance.trace_step(
            "rag.upload", tenant=tenant, extra={"skipped": True, "doc_id": existed.id}
        )
        return existed, True
    if not (title or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请至少选择一个文件")
    if security_level not in LEVELS:
        raise BusinessError(ErrorCode.PARAM_INVALID, "密级仅支持 public/internal/confidential")
    if status not in STATUSES:
        raise BusinessError(ErrorCode.PARAM_INVALID, "状态仅支持 draft/review/published/archived")
    row = KbDoc(
        tenant=tenant,
        title=title.strip()[:200],
        content=content,
        topic=(topic or "").strip()[:64],
        status=status,
        sha256=digest,
        version=1,
        security_level=security_level,
        channels=json.dumps(_parse_channels(channels or ["all"]), ensure_ascii=False),
        valid_from=_parse_date(valid_from, "生效起"),
        valid_to=_parse_date(valid_to, "生效止"),
    )
    db.add(row)
    await db.flush()
    await _write_chunks(db, row.id, split_chunks(content), tenant=tenant)
    await _snapshot_version(db, row, actor=actor, action="create")
    if actor:
        await rag_governance.audit_write(
            db,
            tenant=tenant,
            actor=actor,
            action="kb.upload",
            target=row.id,
            detail={"title": row.title, "sha256": digest},
        )
    await db.commit()
    bump_corpus(tenant)
    rag_governance.trace_step(
        "rag.upload", tenant=tenant, extra={"skipped": False, "doc_id": row.id}
    )
    return row, False


async def ingest_upload(
    db: AsyncSession,
    *,
    tenant: str,
    actor: str,
    filename: str,
    raw: bytes,
    security_level: str = "internal",
    channels: list[str] | None = None,
    valid_from: str = "",
    valid_to: str = "",
    topic: str = "",
    status: str = "published",
) -> tuple[KbDoc, bool]:
    """上传编排（端点唯一入口）：解析（to_thread）→ 去重入库（含切分/向量/审计）。"""
    from app.services import doc_parse_service

    parsed = await asyncio.to_thread(doc_parse_service.parse_upload, filename, raw)
    title = parsed["title"] if parsed["title"] != "未命名文档" else (filename or "未命名文档")
    return await get_or_create_doc(
        db,
        tenant=tenant,
        title=title,
        content=parsed["content"],
        raw=raw,
        actor=actor,
        security_level=security_level,
        channels=channels,
        valid_from=valid_from,
        valid_to=valid_to,
        topic=topic,
        status=status,
    )


async def delete_doc(db: AsyncSession, *, tenant: str, doc_id: str, actor: str = "") -> None:
    """删除文档（跨租户 404；分块+向量级联删；写操作记 audit）。"""
    row = (
        await db.execute(select(KbDoc).where(KbDoc.id == doc_id, KbDoc.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "文档不存在或无权访问", 404)
    old = list((await db.execute(select(KbChunk).where(KbChunk.doc_id == doc_id))).scalars())
    await vector_store.delete_by_chunk(tenant, [c.id for c in old])
    # SQLite 外键级联不可靠，显式删块防孤儿
    await db.execute(delete(KbChunk).where(KbChunk.doc_id == doc_id))
    await db.delete(row)
    if actor:
        await rag_governance.audit_write(
            db, tenant=tenant, actor=actor, action="kb.delete", target=doc_id
        )
    await db.commit()
    bump_corpus(tenant)
    rag_governance.trace_step("rag.delete", tenant=tenant, extra={"doc_id": doc_id})


async def update_doc(
    db: AsyncSession,
    *,
    tenant: str,
    doc_id: str,
    title: str,
    content: str,
    security_level: str,
    channels: list[str] | None,
    valid_from: str = "",
    valid_to: str = "",
    topic: str = "",
    actor: str = "",
) -> KbDoc:
    """编辑文档：内容变则重算 sha（撞他篇 1001）+ 版本 +1；元数据直接覆盖；快照落版本表。"""
    if not (title or "").strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "标题不能为空")
    if security_level not in LEVELS:
        raise BusinessError(ErrorCode.PARAM_INVALID, "密级仅支持 public/internal/confidential")
    row = await get_doc(db, tenant=tenant, doc_id=doc_id)
    digest = sha256_of((content or "").encode("utf-8"))
    content_changed = digest != row.sha256
    if content_changed:
        clash = (
            await db.execute(
                select(KbDoc).where(
                    KbDoc.tenant == tenant, KbDoc.sha256 == digest, KbDoc.id != doc_id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise BusinessError(ErrorCode.PARAM_INVALID, "与其他文档内容重复，已跳过保存")
        row.sha256 = digest
        row.version += 1
    row.title = title.strip()[:200]
    row.content = content or ""
    row.topic = (topic or "").strip()[:64]
    if content_changed:
        old_ids = list(
            (await db.execute(select(KbChunk).where(KbChunk.doc_id == row.id))).scalars()
        )
        await vector_store.delete_by_chunk(tenant, [c.id for c in old_ids])
        await db.execute(delete(KbChunk).where(KbChunk.doc_id == row.id))
        await _write_chunks(db, row.id, split_chunks(row.content), tenant=tenant)
        await _snapshot_version(db, row, actor=actor, action="update")
    row.security_level = security_level
    row.channels = json.dumps(_parse_channels(channels or ["all"]), ensure_ascii=False)
    row.valid_from = _parse_date(valid_from, "生效起")
    row.valid_to = _parse_date(valid_to, "生效止")
    await db.commit()
    bump_corpus(tenant)
    return row
