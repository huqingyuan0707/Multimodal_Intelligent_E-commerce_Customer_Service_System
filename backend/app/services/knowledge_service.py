"""DB 三路召回 RAG 检索（P1 BM25 词汇路，对齐 RAG 规范 §2/§3 + FR-4/FR-13.4）

链路：治理 SQL（租户/密级/已发布）→ 热点缓存 → 生效期/渠道过滤
      → 向量路+BM25 路+关键词路 → RRF 融合 → rerank_service 二阶段精排
      → 多样性裁剪 → 阈值拒答。
BGE 接入替换 vector_store.embed_text，bge-reranker 替换 rerank 体，签名与治理不变。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import get_json, set_json
from app.db.models import KbChunk, KbDoc
from app.services import rag_governance, rerank_service, vector_store
from app.services.knowledge_scoring import (
    _score_chunks,
    _terms,
    bm25_scores,
    rrf_fuse,
    score,
)

# 薄转发：打分纯函数已下沉 knowledge_scoring，单测旧导入口径不变。
__all__ = [
    "_terms",
    "bm25_scores",
    "bump_corpus",
    "retrieve",
    "retrieve_debug",
    "rrf_fuse",
    "score",
    "visible_levels",
]

_DOCS: list[dict[str, object]] | None = None
_DOCS_LOCK = threading.Lock()

# 坐席/运营可见内部文档；机密仅 kb 角色；空角色只见公开
_INTERNAL_ROLES = frozenset({"cs", "ops", "admin", "shop", "stock", "kb"})

# 语料版本（租户级）：文档写操作 bump，缓存键带版本即时失效（多副本至多滞后一个 TTL）
_CORPUS_VER: dict[str, int] = {}


def bump_corpus(tenant: str) -> None:
    """语料版本 +1（document_service 写路径调用；缓存键带版本，天然失效）。"""
    _CORPUS_VER[tenant] = _CORPUS_VER.get(tenant, 0) + 1


def _seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "seed" / "knowledge.json"


def _load_docs_sync() -> list[dict[str, object]]:
    """同步读种子文件（调用方必须走 to_thread，禁止在 async 直接调））。"""
    global _DOCS
    if _DOCS is None:
        with _DOCS_LOCK:
            if _DOCS is None:
                raw = json.loads(_seed_path().read_text(encoding="utf-8"))
                _DOCS = raw if isinstance(raw, list) else []
    return list(_DOCS or [])


def visible_levels(roles: list[str] | None) -> set[str]:
    """密级可见集（纯函数）：公开恒可见；内部限在岗角色；机密仅 kb。"""
    owned = set(roles or [])
    levels = {"public"}
    if owned & _INTERNAL_ROLES:
        levels.add("internal")
    if "kb" in owned:
        levels.add("confidential")
    return levels


class _Hit(TypedDict):
    """内部命中行（score 保持 float，出口转 dict[str, object]）。"""

    title: str
    content: str
    source: str
    score: float


def _rerank(fused: dict[str, float], cosine: dict[str, float]) -> list[str]:
    """分数重排（委托 rerank_service；保留本函数名兼容旧单测导入）。"""
    return rerank_service.rerank(fused, cosine)


def _valid_now(valid_from: object, valid_to: object, now: datetime) -> bool:
    """生效期过滤（委托 rag_governance，保留旧名兼容）。"""
    return rag_governance.is_valid_now(valid_from, valid_to, now)


async def _retrieve_legacy(
    query: str, tenant: str, top_k: int, threshold: float
) -> list[dict[str, object]]:
    """历史种子文件路径（db=None 离线兼容；行为与旧实现一致）。"""
    docs = await asyncio.to_thread(_load_docs_sync)
    scored: list[_Hit] = []
    for doc in docs:
        doc_tenant = str(doc.get("tenant", ""))
        if doc_tenant not in (tenant, "public"):
            continue
        text = f"{doc.get('title', '')} {doc.get('content', '')}"
        s = score(query, text)
        if s >= threshold:
            scored.append(
                {
                    "title": str(doc.get("title", "")),
                    "content": str(doc.get("content", "")),
                    "source": str(doc.get("id", "")),
                    "score": round(s, 4),
                }
            )
    scored.sort(key=lambda d: d["score"], reverse=True)
    return [dict(hit) for hit in scored[:top_k]]


def _governance_filter(
    docs: list[KbDoc], now: datetime, channel: str
) -> tuple[list[KbDoc], int, int]:
    """治理前置过滤（纯函数）：生效期 + 渠道；返回 (保留文档, 过期数, 渠道拦截数)。"""
    kept: list[KbDoc] = []
    n_expired = 0
    n_channel = 0
    for d in docs:
        if not rag_governance.is_valid_now(d.valid_from, d.valid_to, now):
            n_expired += 1
            continue
        if settings.RAG_CHANNEL_FILTER:
            try:
                chs = json.loads(d.channels or "")
                chs = chs if isinstance(chs, list) else ["all"]
            except ValueError:
                chs = ["all"]
            if not rag_governance.channel_visible([str(c) for c in chs], channel):
                n_channel += 1
                continue
        kept.append(d)
    return kept, n_expired, n_channel


def _cache_key(tenant: str, levels: set[str], channel: str, limit: int, query: str) -> str:
    """热点缓存键（租户+可见密级+渠道+条数+query 哈希+语料版本；写操作 bump 即失效）。"""
    digest = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]
    ver = _CORPUS_VER.get(tenant, 0)
    return f"rag:v{ver}:{tenant}:{','.join(sorted(levels))}:{channel}:{limit}:{digest}"


async def _retrieve_core(
    query: str,
    tenant: str,
    limit: int,
    floor: float,
    db: AsyncSession,
    roles: list[str] | None,
    channel: str,
    trace_id: str,
) -> tuple[list[dict[str, object]], dict[str, Any]]:
    """检索内核：返回 (refs, meta)；meta 含过滤计数/缓存命中，供 retrieve 与 debug 复用。"""
    levels = visible_levels(roles)
    now = datetime.now()
    docs = list(
        (
            await db.execute(
                select(KbDoc).where(
                    KbDoc.tenant == tenant,
                    KbDoc.security_level.in_(levels),
                    KbDoc.status == "published",
                )
            )
        ).scalars()
    )
    total_docs = len(docs)
    docs, n_expired, n_channel = _governance_filter(docs, now, channel)
    if not docs:
        meta = {
            "total_docs": total_docs,
            "chunks": 0,
            "expired": n_expired,
            "channel_cut": n_channel,
            "best": 0.0,
            "refs": 0,
            "vec_ok": False,
            "cached": False,
        }
        rag_governance.trace_step("rag.retrieve", tenant=tenant, trace_id=trace_id, extra=meta)
        return [], meta
    doc_ids = [d.id for d in docs]
    chunks = list((await db.execute(select(KbChunk).where(KbChunk.doc_id.in_(doc_ids)))).scalars())
    bm25_raw, kw_scores, chunk_by_id, by_doc = _score_chunks(query, docs, chunks)
    try:
        vec_scores = await vector_store.search(tenant, query, [c.id for c in chunks])
        vec_ok = True
    except Exception:
        vec_scores = {}
        vec_ok = False
    bm25_rank = sorted(bm25_raw, key=lambda key: bm25_raw[key], reverse=True)
    keyword_rank = sorted(kw_scores, key=lambda key: kw_scores[key], reverse=True)
    ranks: list[list[str]] = [bm25_rank, keyword_rank]
    if settings.VECTOR_FUSE_RANK and vec_ok and any(v > 0 for v in vec_scores.values()):
        ranks.insert(0, sorted(vec_scores, key=lambda k: vec_scores[k], reverse=True))
    fused = rrf_fuse(ranks)
    titles = {cid: by_doc[chunk_by_id[cid].doc_id].title for cid in chunk_by_id}
    ordered = rerank_service.rerank(
        fused, kw_scores, bm25=bm25_raw, vector=vec_scores, titles=titles, query=query
    )
    # 多样性裁剪：同 doc 至多 RAG_DIVERSITY_PER_DOC 个块
    picked: list[str] = []
    per_doc: dict[str, int] = {}
    for key in ordered:
        doc_id = chunk_by_id[key].doc_id
        if per_doc.get(doc_id, 0) >= settings.RAG_DIVERSITY_PER_DOC:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        picked.append(key)
        if len(picked) >= limit:
            break
    # 相关性门禁看关键词交叠（0-1 绝对口径；BM25 归一后恒 1 会抬进无据，哈希向量只排不用）
    best = max(kw_scores[k] for k in picked) if picked else 0.0
    top_bm25 = max(bm25_raw.values()) if bm25_raw else 0.0
    if not picked or best < floor:
        meta = {
            "total_docs": total_docs,
            "chunks": len(chunks),
            "expired": n_expired,
            "channel_cut": n_channel,
            "best": round(best, 4),
            "refs": 0,
            "vec_ok": vec_ok,
            "cached": False,
        }
        rag_governance.trace_step("rag.retrieve", tenant=tenant, trace_id=trace_id, extra=meta)
        return [], meta
    refs: list[dict[str, object]] = []
    for key in picked:
        chunk = chunk_by_id[key]
        doc = by_doc[chunk.doc_id]
        refs.append(
            {
                "title": doc.title,
                "content": chunk.content,
                "source": f"{doc.id}#{chunk.ord}",
                "doc_id": doc.id,
                "score": round(bm25_raw[key] / top_bm25, 4) if top_bm25 > 0 else 0.0,
                "bm25": round(bm25_raw[key], 4),
                "kw": round(kw_scores[key], 4),
                "rrf": round(fused.get(key, 0.0), 4),
                "vector_score": round(vec_scores.get(key, 0.0), 4),
            }
        )
    meta = {
        "total_docs": total_docs,
        "chunks": len(chunks),
        "expired": n_expired,
        "channel_cut": n_channel,
        "best": round(best, 4),
        "refs": len(refs),
        "vec_ok": vec_ok,
        "cached": False,
    }
    rag_governance.trace_step("rag.retrieve", tenant=tenant, trace_id=trace_id, extra=meta)
    return refs, meta


async def retrieve(
    query: str,
    tenant: str,
    top_k: int | None = None,
    threshold: float | None = None,
    db: AsyncSession | None = None,
    roles: list[str] | None = None,
    channel: str = "all",
    trace_id: str = "",
) -> list[dict[str, object]]:
    """统一检索入口：热点缓存 → 三路召回（向量库+BM25+关键词）→ RRF → 精排 → 治理 → 阈值。

    每步留痕：trace_step 带 tenant/trace_id（读步骤不写 DB）；过滤原因计入 trace。
    channel 走 Settings.RAG_CHANNEL_FILTER 开关；向量缺失自动回退双路，不断流。
    """
    limit = top_k if top_k is not None else settings.TOP_K
    if db is None:
        return await _retrieve_legacy(query, tenant, limit, 0.12)
    floor = threshold if threshold is not None else settings.RAG_DB_THRESHOLD
    levels = visible_levels(roles)
    ttl = settings.RAG_CACHE_TTL
    key = _cache_key(tenant, levels, channel, limit, query)
    if ttl > 0:
        try:
            hit = await get_json(key)
            if isinstance(hit, list):
                rag_governance.trace_step(
                    "rag.retrieve",
                    tenant=tenant,
                    trace_id=trace_id,
                    extra={"refs": len(hit), "cached": True},
                )
                return [dict(item) for item in hit if isinstance(item, dict)]
        except Exception:
            pass
    refs, _meta = await _retrieve_core(query, tenant, limit, floor, db, roles, channel, trace_id)
    if ttl > 0:
        with contextlib.suppress(Exception):
            await set_json(key, refs, ttl)
    return refs


async def retrieve_debug(
    query: str,
    tenant: str,
    db: AsyncSession,
    roles: list[str] | None = None,
    channel: str = "all",
    top_k: int | None = None,
) -> dict[str, object]:
    """检索测试口径：返回引用（含各路分数）+ 过滤原因（运营后台预览召回分数/拦截原因）。"""
    limit = top_k if top_k is not None else settings.TOP_K
    refs, meta = await _retrieve_core(
        query, tenant, limit, settings.RAG_DB_THRESHOLD, db, roles, channel, ""
    )
    return {
        "refs": refs,
        "levels": sorted(visible_levels(roles)),
        "channel": channel,
        "filtered": {
            "total_docs": meta["total_docs"],
            "expired": meta["expired"],
            "channel_cut": meta["channel_cut"],
            "below_threshold": meta["refs"] == 0,
        },
    }
