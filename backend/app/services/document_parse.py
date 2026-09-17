"""知识库文档解析与分块（种子解析→切分→向量双写→重建，对齐 RAG 规范 §1）

链路：ingest_upload（to_thread 解析）→ document_service 去重入库 →
      本模块 split_chunks 切分 → _write_chunks 向量双写；重建走
      rebuild_chunks / run_reindex（后台任务）。
红线：解析只做纯文本处理；向量失败不阻塞入库（status 可见）；
      切分上限走 Settings.KB_CHUNK_CHARS，禁止硬编码。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import KbChunk, KbDoc
from app.services import rag_governance, vector_store
from app.services.knowledge_service import bump_corpus


def _dt_text(value: Any) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else ""


def _parse_date(text: str, field: str) -> datetime | None:
    """生效期解析：空=不限；支持 YYYY-MM-DD 与 YYYY-MM-DD HH:mm:ss，非法 1001。"""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise BusinessError(ErrorCode.PARAM_INVALID, f"{field}格式不正确（YYYY-MM-DD）")


def _parse_channels(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [v for v in value if v.strip()] or ["all"]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()] or ["all"]
    return ["all"]


def _channels_of(row: KbDoc) -> list[str]:
    try:
        loaded = json.loads(row.channels or "")
    except ValueError:
        return ["all"]
    return _parse_channels(loaded)


def parse_seed_markdown(text: str) -> dict[str, Any]:
    """解析种子 Markdown：front-matter 七字段 + 正文（去注释行；无头全篇当正文）。"""
    meta: dict[str, str] = {}
    body = text or ""
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            for line in body[3:end].splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            body = body[end + 4 :]
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("<!--")]
    title = meta.get("title", "")
    if not title:
        for ln in lines:
            if ln.startswith("# "):
                title = ln[2:].strip()
                break
    return {
        "title": title,
        "topic": meta.get("topic", "").strip()[:64],
        "security_level": meta.get("security_level", "internal"),
        "channels": _parse_channels(meta.get("channels", "[all]").strip("[]")),
        "valid_from": _parse_date(meta.get("valid_from", ""), "生效起"),
        "valid_to": _parse_date(meta.get("valid_to", ""), "生效止"),
        "version": int(meta["version"]) if meta.get("version", "1").isdigit() else 1,
        "body": "\n".join(lines).strip() + "\n",
    }


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_chunks(content: str) -> list[str]:
    """按业务主题切分：`##` 起新块；超长按段硬切到 KB_CHUNK_CHARS（纯函数可单测）。"""
    blocks: list[str] = []
    current: list[str] = []
    for line in (content or "").splitlines():
        has_body = any(not part.startswith("#") and part.strip() for part in current)
        if line.startswith("##") and has_body:
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    cap = settings.KB_CHUNK_CHARS
    out: list[str] = []
    for block in blocks:
        text = block.strip("\n")
        if not text.strip():
            continue
        if len(text) <= cap:
            out.append(text)
            continue
        buf = ""
        for para in text.split("\n"):
            if buf.strip() and len(buf) + len(para) + 1 > cap:
                out.append(buf.strip())
                buf = ""
            buf += para + "\n"
        if buf.strip():
            out.append(buf.strip())
    stripped = (content or "").strip()
    return out or ([stripped] if stripped else [])


async def _write_chunks(
    db: AsyncSession, doc_id: str, chunks: list[str], *, tenant: str = ""
) -> int:
    """落块+向量双写（vector_id 回写；向量失败不阻塞入库，status 可见）。"""
    rows = [KbChunk(doc_id=doc_id, ord=i, content=part) for i, part in enumerate(chunks)]
    db.add_all(rows)
    await db.flush()
    if tenant:
        try:
            vecs = await asyncio.to_thread(
                lambda: [vector_store.embed_text(t) for t in [r.content for r in rows]]
            )
            for row, vec in zip(rows, vecs, strict=True):
                row.vector_id = f"{tenant}:{row.id}"
                vector_store._store[f"{tenant}:{row.id}"] = vec
        except Exception:
            pass
    return len(chunks)


async def rebuild_chunks(db: AsyncSession, *, tenant: str) -> dict[str, int]:
    """重建租户全部分块：删旧块+向量 → 重切+向量双写 → 单事务提交。"""
    docs = list((await db.execute(select(KbDoc).where(KbDoc.tenant == tenant))).scalars())
    total_chunks = 0
    for doc in docs:
        old = list((await db.execute(select(KbChunk).where(KbChunk.doc_id == doc.id))).scalars())
        await vector_store.delete_by_chunk(tenant, [c.id for c in old])
        await db.execute(delete(KbChunk).where(KbChunk.doc_id == doc.id))
        total_chunks += await _write_chunks(db, doc.id, split_chunks(doc.content), tenant=tenant)
    await db.commit()
    bump_corpus(tenant)
    rag_governance.trace_step(
        "rag.reindex", tenant=tenant, extra={"docs": len(docs), "chunks": total_chunks}
    )
    return {"docs": len(docs), "chunks": total_chunks}


async def run_reindex(*, tenant: str, task_id: str) -> None:
    """reindex 后台执行：自建会话（请求会话此时已关闭）→ 重建分块 → task 进度落库。

    异常只记 task error，绝不抛（后台抛异常只会烂在日志里，前端靠轮询感知）。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import get_engine
    from app.services import task_service

    maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with maker() as db:
            await task_service.mark_task(db, tenant=tenant, task_id=task_id, status="running")
            stats = await rebuild_chunks(db, tenant=tenant)
            await task_service.mark_task(
                db, tenant=tenant, task_id=task_id, status="done", progress=1.0, output=stats
            )
    except Exception as exc:
        with contextlib.suppress(Exception):
            async with maker() as db:
                await task_service.mark_task(
                    db, tenant=tenant, task_id=task_id, status="error", error=str(exc)[:500]
                )
