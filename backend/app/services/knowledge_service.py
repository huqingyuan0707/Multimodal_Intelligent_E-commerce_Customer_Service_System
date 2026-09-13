"""DB 双路召回 RAG 检索（P0 stdlib 链路，对齐 RAG 规范 §2/§3）

链路：kb_docs + kb_chunks（租户/密级/生效期过滤）
      → 向量路（bigram TF-IDF 余弦）+ 关键词路（标题加权交叠）
      → RRF 融合 → 分数重排 → 多样性裁剪 → 阈值拒答。
BGE / bge-reranker 接入时替换 _cosine 与 _rerank 即可，签名与治理不变。
db=None 时走历史种子文件路径（离线单测兼容，不走 DB）。
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
    """分数重排（bge-reranker P1 替换点）：RRF 主序 + 余弦打破平局 + 归一备用。"""
    return sorted(fused, key=lambda key: (fused[key], cosine.get(key, 0.0)), reverse=True)


def _valid_now(valid_from: object, valid_to: object, now: datetime) -> bool:
    """生效期过滤：空端不限；naive 时间统一按 UTC 裸值比较（落库口径）。"""
    before_start = isinstance(valid_from, datetime) and now < valid_from.replace(tzinfo=None)
    after_end = isinstance(valid_to, datetime) and now > valid_to.replace(tzinfo=None)
    return not (before_start or after_end)


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


async def retrieve(
    query: str,
    tenant: str,
    top_k: int | None = None,
    threshold: float | None = None,
    db: AsyncSession | None = None,
    roles: list[str] | None = None,
) -> list[dict[str, object]]:
    """统一检索入口：有 db 走 DB 双路链，db=None 走历史种子路径（阈值默认不变）。"""
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
    docs = [d for d in docs if _valid_now(d.valid_from, d.valid_to, now)]
    if not docs:
        return []
    doc_ids = [d.id for d in docs]
    chunks = list((await db.execute(select(KbChunk).where(KbChunk.doc_id.in_(doc_ids)))).scalars())
    by_doc = {d.id: d for d in docs}
    # IDF 在候选块上现算（百级块毫秒级；万级以上切向量库，见 RAG 规范）
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
    vector_rank = sorted(cosine, key=lambda key: cosine[key], reverse=True)
    keyword_rank = sorted(kw_scores, key=lambda key: kw_scores[key], reverse=True)
    fused = rrf_fuse([vector_rank, keyword_rank])
    ordered = _rerank(fused, cosine)
    # 多样性裁剪：同 doc 至多 RAG_DIVERSITY_PER_DOC 个块
    chunk_by_id = {c.id: c for c in chunks}
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
    # 相关性门禁取双路最高分（余弦易被长块稀释，关键词交叠保召回下限）
    if not picked or max(max(cosine[key], kw_scores[key]) for key in picked) < floor:
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
            }
        )
    return refs
