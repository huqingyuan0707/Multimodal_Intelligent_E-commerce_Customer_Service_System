"""DB 三路召回 RAG 检索（P0 stdlib 链路，对齐 RAG 规范 §2/§3）

链路：治理 SQL（租户/密级）→ 生效期/渠道过滤 → 向量路+TF-IDF 路+关键词路
      → RRF 融合 → rerank_service 重排 → 多样性裁剪 → 阈值拒答。
BGE 接入替换 vector_store.embed_text，bge-reranker 替换 rerank 体，签名与治理不变。
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KbChunk, KbDoc
from app.services import rag_governance, rerank_service, vector_store

_DOCS: list[dict[str, object]] | None = None
_DOCS_LOCK = threading.Lock()

# 坐席/运营可见内部文档；机密仅 kb 角色；空角色只见公开
_INTERNAL_ROLES = frozenset({"cs", "ops", "admin", "shop", "stock", "kb"})


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


def _bigrams(text: str) -> set[str]:
    chars = [c for c in text.strip() if not c.isspace()]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def score(query: str, doc_text: str) -> float:
    """bigram 重叠率 0-1，纯函数可单测（关键词路基础分）。"""
    q, d = _bigrams(query), _bigrams(doc_text)
    if not q:
        return 0.0
    return len(q & d) / len(q)


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


def _cosine(query_bi: set[str], doc_bi: set[str], idf: dict[str, float]) -> float:
    """bigram TF-IDF 余弦（向量路；二值 TF，idf 平滑，纯 Python 无依赖）。"""
    common = query_bi & doc_bi
    if not common:
        return 0.0
    num = sum(idf.get(t, 1.0) ** 2 for t in common)
    q_norm = math.sqrt(sum(idf.get(t, 1.0) ** 2 for t in query_bi))
    d_norm = math.sqrt(sum(idf.get(t, 1.0) ** 2 for t in doc_bi))
    if q_norm == 0.0 or d_norm == 0.0:
        return 0.0
    return num / (q_norm * d_norm)


def _keyword_score(query: str, title: str, text: str) -> float:
    """关键词路：正文交叠 0.7 + 标题交叠 0.3（标题命中是强信号）。"""
    return 0.7 * score(query, text) + 0.3 * score(query, title)


def rrf_fuse(rank_lists: list[list[str]], k: int | None = None) -> dict[str, float]:
    """RRF 融合：score = Σ 1/(K + rank)，纯函数可单测（K 走 Settings.RRF_K）。"""
    kk = k if k is not None else settings.RRF_K
    fused: dict[str, float] = {}
    for ranking in rank_lists:
        for rank, key in enumerate(ranking, 1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (kk + rank)
    return fused


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


def _score_chunks(
    query: str, docs: list[KbDoc], chunks: list[KbChunk]
) -> tuple[dict[str, float], dict[str, float], dict[str, KbChunk], dict[str, KbDoc]]:
    """双路打分（纯函数）：TF-IDF 余弦 + 关键词分；IDF 在候选块上现算（百级块毫秒级，见 RAG 规范）。"""
    by_doc = {d.id: d for d in docs}
    doc_freq: dict[str, int] = {}
    chunk_bi: dict[str, set[str]] = {}
    for chunk in chunks:
        bis = _bigrams(chunk.content)
        chunk_bi[chunk.id] = bis
        for term in bis:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    total = max(len(chunks), 1)
    idf = {term: math.log((total + 1) / (freq + 1)) + 1.0 for term, freq in doc_freq.items()}
    query_bi = _bigrams(query)
    cosine: dict[str, float] = {}
    kw_scores: dict[str, float] = {}
    for chunk in chunks:
        doc = by_doc[chunk.doc_id]
        cosine[chunk.id] = _cosine(query_bi, chunk_bi[chunk.id], idf)
        kw_scores[chunk.id] = _keyword_score(query, doc.title, chunk.content)
    return cosine, kw_scores, {c.id: c for c in chunks}, by_doc


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
    """统一检索入口：三路召回（向量库+TF-IDF+关键词）→ RRF → 重排 → 治理 → 阈值。

    每步留痕：trace_step 带 tenant/trace_id（读步骤不写 DB）；过滤原因计入 trace。
    channel 走 Settings.RAG_CHANNEL_FILTER 开关；向量缺失自动回退双路，不断流。
    """
    limit = top_k if top_k is not None else settings.TOP_K
    if db is None:
        return await _retrieve_legacy(query, tenant, limit, 0.12)
    floor = threshold if threshold is not None else settings.RAG_DB_THRESHOLD
    levels = visible_levels(roles)
    now = datetime.now()
    docs = list(
        (
            await db.execute(
                select(KbDoc).where(KbDoc.tenant == tenant, KbDoc.security_level.in_(levels))
            )
        ).scalars()
    )
    total_docs = len(docs)
    docs, n_expired, n_channel = _governance_filter(docs, now, channel)
    if not docs:
        rag_governance.trace_step(
            "rag.retrieve",
            tenant=tenant,
            trace_id=trace_id,
            extra={
                "total_docs": total_docs,
                "expired": n_expired,
                "channel_cut": n_channel,
                "refs": 0,
            },
        )
        return []
    doc_ids = [d.id for d in docs]
    chunks = list((await db.execute(select(KbChunk).where(KbChunk.doc_id.in_(doc_ids)))).scalars())
    cosine, kw_scores, chunk_by_id, by_doc = _score_chunks(query, docs, chunks)
    try:
        vec_scores = await vector_store.search(tenant, query, [c.id for c in chunks])
        vec_ok = True
    except Exception:
        vec_scores = {}
        vec_ok = False
    tfidf_rank = sorted(cosine, key=lambda key: cosine[key], reverse=True)
    keyword_rank = sorted(kw_scores, key=lambda key: kw_scores[key], reverse=True)
    ranks: list[list[str]] = [tfidf_rank, keyword_rank]
    if settings.VECTOR_FUSE_RANK and vec_ok and any(v > 0 for v in vec_scores.values()):
        ranks.insert(0, sorted(vec_scores, key=lambda k: vec_scores[k], reverse=True))
    fused = rrf_fuse(ranks)
    ordered = rerank_service.rerank(fused, cosine, kw_scores)
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
    # 相关性门禁只看 TF-IDF/关键词（哈希向量碰撞率高，只参与排序不参与门禁，避免无据被抬进）
    best = max(max(cosine[k], kw_scores[k]) for k in picked) if picked else 0.0
    if not picked or best < floor:
        rag_governance.trace_step(
            "rag.retrieve",
            tenant=tenant,
            trace_id=trace_id,
            extra={
                "total_docs": total_docs,
                "chunks": len(chunks),
                "best": round(best, 4),
                "refs": 0,
            },
        )
        return []
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
                "score": round(cosine[key], 4),
                "vector_score": round(vec_scores.get(key, 0.0), 4),
            }
        )
    rag_governance.trace_step(
        "rag.retrieve",
        tenant=tenant,
        trace_id=trace_id,
        extra={
            "total_docs": total_docs,
            "chunks": len(chunks),
            "refs": len(refs),
            "vec_ok": vec_ok,
        },
    )
    return refs


async def retrieve_debug(
    query: str, tenant: str, db: AsyncSession, roles: list[str] | None = None, channel: str = "all"
) -> dict[str, object]:
    """检索测试口径：返回引用 + 过滤原因（运营后台预览召回分数/拦截原因）。"""
    refs = await retrieve(query, tenant, db=db, roles=roles, channel=channel)
    return {"refs": refs, "levels": sorted(visible_levels(roles)), "channel": channel}
