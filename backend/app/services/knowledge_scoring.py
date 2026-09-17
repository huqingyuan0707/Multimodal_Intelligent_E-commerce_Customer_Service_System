"""RAG 三路打分纯函数（中文 bigram/BM25/RRF/关键词，对齐 RAG 规范 §2/§3）

链路：knowledge_service._retrieve_core → 本模块 _score_chunks（三路原始分）
      → RRF 融合 → rerank_service 精排 → 阈值拒答。
红线：本模块只做纯计算（settings 读参 + models 类型），不碰 DB/网络；
      DB 语料版本与缓存键仍归 knowledge_service。
"""

from __future__ import annotations

import math
from collections import Counter

from app.config import settings
from app.db.models import KbChunk, KbDoc


def _bigrams(text: str) -> set[str]:
    chars = [c for c in text.strip() if not c.isspace()]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _terms(text: str) -> list[str]:
    """BM25 词项：中文按 bigram，还保持纯 stdlib（与 _bigrams 同一切分口径）。"""
    chars = [c for c in (text or "").strip() if not c.isspace()]
    if len(chars) < 2:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def score(query: str, doc_text: str) -> float:
    """bigram 重叠率 0-1，纯函数可单测（关键词路基础分）。"""
    q, d = _bigrams(query), _bigrams(doc_text)
    if not q:
        return 0.0
    return len(q & d) / len(q)


def bm25_scores(
    query_terms: list[str],
    chunk_tf: dict[str, Counter[str]],
    doc_freq: dict[str, int],
    avg_len: float,
    total: int,
) -> dict[str, float]:
    """BM25 词汇打分（P1 替换 TF-IDF 余弦；k1/b 走 Settings，纯函数可单测）。"""
    k1 = settings.BM25_K1
    b = settings.BM25_B
    idf: dict[str, float] = {}
    for term in set(query_terms):
        df = doc_freq.get(term, 0)
        idf[term] = math.log((total - df + 0.5) / (df + 0.5) + 1.0)
    out: dict[str, float] = {}
    for cid, tf in chunk_tf.items():
        length = float(sum(tf.values())) or 1.0
        norm = (1.0 - b + b * length / avg_len) if avg_len > 0 else 1.0
        total_s = 0.0
        for term in set(query_terms):
            freq = tf.get(term, 0)
            if not freq:
                continue
            total_s += idf[term] * freq * (k1 + 1.0) / (freq + k1 * norm)
        out[cid] = total_s
    return out


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


def _score_chunks(
    query: str, docs: list[KbDoc], chunks: list[KbChunk]
) -> tuple[dict[str, float], dict[str, float], dict[str, KbChunk], dict[str, KbDoc]]:
    """三路打分输入（纯函数）：BM25 原始分 + 关键词分；IDF/平均长度在候选块上现算。

    返回 (bm25_raw, kw_scores, chunk_by_id, by_doc)；归一化与门禁由调用方做。
    """
    by_doc = {d.id: d for d in docs}
    doc_freq: dict[str, int] = {}
    chunk_tf: dict[str, Counter[str]] = {}
    total_len = 0
    for chunk in chunks:
        tf = Counter(_terms(chunk.content))
        chunk_tf[chunk.id] = tf
        total_len += sum(tf.values())
        for term in tf:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    total = max(len(chunks), 1)
    avg_len = total_len / total if total else 0.0
    bm25 = bm25_scores(_terms(query), chunk_tf, doc_freq, avg_len, total)
    kw_scores: dict[str, float] = {}
    for chunk in chunks:
        doc = by_doc[chunk.doc_id]
        kw_scores[chunk.id] = _keyword_score(query, doc.title, chunk.content)
    return bm25, kw_scores, {c.id: c for c in chunks}, by_doc
