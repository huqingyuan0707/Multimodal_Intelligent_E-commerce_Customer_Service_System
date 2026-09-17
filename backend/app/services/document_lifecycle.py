"""知识库文档生命周期（版本快照→回滚→审核流转→引用统计，对齐 FR-13.2/FR-13.5）

链路：上传/编辑写快照 → list_versions 查历史 → rollback_doc 另起新版恢复；
      submit/publish/archive/reopen 经 transition_doc 流转（发布需换人复核）；
      doc_stats 按主题聚合引用 + 30 天零引用提示复核。
红线：一切查询带 tenant（跨租户 404 不泄露存在性）；回滚不覆盖旧版；
      写操作 bump 语料版本即时失效检索缓存。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import KbChunk, KbDoc, KbDocVersion, Message
from app.services import rag_governance, vector_store
from app.services.document_parse import _dt_text, _write_chunks, split_chunks
from app.services.knowledge_service import bump_corpus


async def get_doc(db: AsyncSession, *, tenant: str, doc_id: str) -> KbDoc:
    """取单篇（跨租户 404；预览/编辑前置）。"""
    row = (
        await db.execute(select(KbDoc).where(KbDoc.id == doc_id, KbDoc.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "文档不存在或无权访问", 404)
    return row


async def _snapshot_version(db: AsyncSession, row: KbDoc, *, actor: str, action: str) -> None:
    """版本快照只追加（新建/编辑/发布/回滚各一行；回滚读它恢复）。"""
    db.add(
        KbDocVersion(
            tenant=row.tenant,
            doc_id=row.id,
            version=row.version,
            title=row.title,
            content=row.content,
            sha256=row.sha256,
            actor=actor or "",
            action=action,
        )
    )
    await db.flush()


def _version_to_dict(row: KbDocVersion) -> dict[str, Any]:
    return {
        "version": row.version,
        "title": row.title,
        "content": row.content,
        "sha256": row.sha256,
        "actor": row.actor,
        "action": row.action,
        "created_at": _dt_text(row.created_at),
    }


async def list_versions(db: AsyncSession, *, tenant: str, doc_id: str) -> list[dict[str, Any]]:
    """版本历史倒序（跨租户 404；回滚/版本抽屉数据源）。"""
    await get_doc(db, tenant=tenant, doc_id=doc_id)
    rows = list(
        (
            await db.execute(
                select(KbDocVersion)
                .where(KbDocVersion.tenant == tenant, KbDocVersion.doc_id == doc_id)
                .order_by(KbDocVersion.version.desc())
            )
        ).scalars()
    )
    return [_version_to_dict(r) for r in rows]


async def rollback_doc(
    db: AsyncSession, *, tenant: str, doc_id: str, version: int, actor: str = ""
) -> KbDoc:
    """回滚到历史版本（FR-13.2：旧内容另起新版本，不覆盖旧版；分块重建+审计）。

    回滚即切回：内容/标题/sha 取目标版本快照，version 在现行基础上 +1 落新快照。
    """
    row = await get_doc(db, tenant=tenant, doc_id=doc_id)
    snap = (
        await db.execute(
            select(KbDocVersion).where(
                KbDocVersion.tenant == tenant,
                KbDocVersion.doc_id == doc_id,
                KbDocVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if snap is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "目标版本不存在", 404)
    if snap.sha256 == row.sha256:
        raise BusinessError(ErrorCode.PARAM_INVALID, "已是该版本内容，无需回滚")
    row.title = snap.title
    row.content = snap.content
    row.sha256 = snap.sha256
    row.version = (row.version or 0) + 1
    old = list((await db.execute(select(KbChunk).where(KbChunk.doc_id == row.id))).scalars())
    await vector_store.delete_by_chunk(tenant, [c.id for c in old])
    await db.execute(delete(KbChunk).where(KbChunk.doc_id == row.id))
    await _write_chunks(db, row.id, split_chunks(row.content), tenant=tenant)
    await _snapshot_version(db, row, actor=actor, action="rollback")
    if actor:
        await rag_governance.audit_write(
            db,
            tenant=tenant,
            actor=actor,
            action="kb.rollback",
            target=doc_id,
            detail={"from_version": snap.version, "to_version": row.version},
        )
    await db.commit()
    bump_corpus(tenant)
    rag_governance.trace_step(
        "rag.rollback", tenant=tenant, extra={"doc_id": doc_id, "version": row.version}
    )
    return row


async def transition_doc(
    db: AsyncSession, *, tenant: str, doc_id: str, action: str, actor: str = ""
) -> KbDoc:
    """生命周期流转（FR-13.2）：submit(draft→review)/publish(review→published，换人复核)
    /archive(published→archived)/reopen(archived→draft)；非法流转 1001 中文提示。"""
    row = await get_doc(db, tenant=tenant, doc_id=doc_id)
    status = row.status or "published"
    if action == "submit":
        if status != "draft":
            raise BusinessError(ErrorCode.PARAM_INVALID, "仅草稿可提交审核")
        row.status = "review"
        row.submitted_by = actor
    elif action == "publish":
        if status != "review":
            raise BusinessError(ErrorCode.PARAM_INVALID, "仅审核中可发布")
        if row.submitted_by and row.submitted_by == actor:
            raise BusinessError(ErrorCode.PARAM_INVALID, "发布需换一位运营复核，不能自己审自己")
        row.status = "published"
        row.published_by = actor
        await _snapshot_version(db, row, actor=actor, action="publish")
    elif action == "archive":
        if status != "published":
            raise BusinessError(ErrorCode.PARAM_INVALID, "仅已发布可归档")
        row.status = "archived"
    elif action == "reopen":
        if status != "archived":
            raise BusinessError(ErrorCode.PARAM_INVALID, "仅已归档可重开为草稿")
        row.status = "draft"
        row.submitted_by = ""
    else:
        raise BusinessError(ErrorCode.PARAM_INVALID, "动作仅支持 submit/publish/archive/reopen")
    if actor:
        await rag_governance.audit_write(
            db,
            tenant=tenant,
            actor=actor,
            action="kb.status",
            target=doc_id,
            detail={"from": status, "to": row.status},
        )
    await db.commit()
    bump_corpus(tenant)
    return row


async def doc_stats(db: AsyncSession, *, tenant: str) -> dict[str, Any]:
    """引用统计（FR-13.5）：按主题聚合引用命中 + 引用为 0 超 30 天提示复核/归档。

    引用口径：messages.citations（问答落库引用）中 doc_id/source 出现即一次引用；
    扫描上限走 Settings.RAG_STATS_SCAN_LIMIT；纯读不写 DB。
    """
    docs = list((await db.execute(select(KbDoc).where(KbDoc.tenant == tenant))).scalars())
    by_status: dict[str, int] = {}
    for d in docs:
        by_status[d.status or "published"] = by_status.get(d.status or "published", 0) + 1
    cited: dict[str, int] = {}
    limit = max(int(settings.RAG_STATS_SCAN_LIMIT or 5000), 1)
    rows = list(
        (
            await db.execute(
                select(Message).where(Message.tenant == tenant).order_by(Message.created_at.desc())
            )
        ).scalars()
    )
    for msg in rows[:limit]:
        try:
            items = json.loads(msg.citations or "[]")
        except ValueError:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("doc_id") or "").strip()
            if not doc_id:
                source = str(item.get("source") or "")
                doc_id = source.split("#")[0].strip()
            if doc_id:
                cited[doc_id] = cited.get(doc_id, 0) + 1
    now = datetime.now()
    topics: dict[str, dict[str, int]] = {}
    idle: list[dict[str, Any]] = []
    for d in docs:
        topic = (d.topic or "").strip() or "未分类"
        bucket = topics.setdefault(topic, {"docs": 0, "cited": 0})
        bucket["docs"] += 1
        hits = cited.get(d.id, 0)
        bucket["cited"] += hits
        created = d.created_at or now
        days_idle = (now - created).days if hits == 0 else 0
        if hits == 0 and (now - created).days > 30 and (d.status or "published") == "published":
            idle.append(
                {
                    "doc_id": d.id,
                    "title": d.title,
                    "topic": topic,
                    "created_at": _dt_text(d.created_at),
                    "days_idle": days_idle,
                }
            )
    idle.sort(key=lambda r: int(r["days_idle"]), reverse=True)
    return {
        "total": len(docs),
        "by_status": by_status,
        "cited": cited,
        "topics": [
            {"topic": name, "docs": stat["docs"], "cited": stat["cited"]}
            for name, stat in sorted(topics.items())
        ],
        "idle_review": idle[:100],
    }
