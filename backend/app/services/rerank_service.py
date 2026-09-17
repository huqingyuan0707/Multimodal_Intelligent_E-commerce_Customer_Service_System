"""二阶段精排（检索第 6 步 Rerank，对齐 RAG 规范 §2 + FR-4）

链路：RRF 融合分（主序）+ BM25/关键词/向量/标题命中四特征加权破平局
      → knowledge_service 做多样性裁剪。
红线：P0 纯 Python（bge-reranker P1 替换 rerank 体即可）；status() 供治理巡检；
      精排只破平局：特征分缩放到最小 RRF 间隙一半以内，绝不推翻 RRF 主序。
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from app.config import settings


def _norm(scores: dict[str, float]) -> dict[str, float]:
    """归一到 0-1（全 0 则全 0，避免除零）。"""
    top = max(scores.values()) if scores else 0.0
    if top <= 0:
        return dict.fromkeys(scores, 0.0)
    return {k: v / top for k, v in scores.items()}


def _bigrams(text: str) -> set[str]:
    """邻接 bigram（与 knowledge_service 同一切分口径，模块解耦各一份）。"""
    chars = [c for c in (text or "").strip() if not c.isspace()]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _title_hit(query: str, title: str) -> bool:
    """标题命中：query 与标题有 bigram 交叠即加分（纯函数可单测）。"""
    if not query or not title:
        return False
    return bool(_bigrams(query) & _bigrams(title))


def rerank(
    fused: dict[str, float],
    second: dict[str, float] | None = None,
    keyword: dict[str, float] | None = None,
    *,
    bm25: dict[str, float] | None = None,
    vector: dict[str, float] | None = None,
    titles: dict[str, str] | None = None,
    query: str = "",
) -> list[str]:
    """二阶段精排：RRF 主序 + 四特征加权破平局（纯函数可单测）。

    second/keyword 保留旧二三位置参兼容（旧余弦/关键词分，并入关键词权重）。
    特征分总和缩放到 RRF 最小正间隙一半以内：只破平局，不推翻主序。
    """
    if not fused:
        return []
    bm25_n = _norm(bm25 or {})
    vec_n = _norm(vector or {})
    kw_raw: dict[str, float] = {}
    for source in (second or {}, keyword or {}):
        for k, v in source.items():
            kw_raw[k] = max(kw_raw.get(k, 0.0), v)
    kw_n = _norm(kw_raw)
    titles = titles or {}
    combo: dict[str, float] = {}
    for key in fused:
        title_bonus = settings.RERANK_TITLE_BONUS if _title_hit(query, titles.get(key, "")) else 0.0
        combo[key] = (
            settings.RERANK_W_BM25 * bm25_n.get(key, 0.0)
            + settings.RERANK_W_KW * kw_n.get(key, 0.0)
            + settings.RERANK_W_VEC * vec_n.get(key, 0.0)
            + title_bonus
        )
    ordered_vals = sorted(set(fused.values()), reverse=True)
    gaps = [a - b for a, b in pairwise(ordered_vals) if a - b > 0]
    # 有明显 RRF 间隙时特征分只够破近似平局；RRF 完全打平则由特征分全权决定
    cap = (min(gaps) / 2.0) if gaps else 1.0
    top_combo = max(combo.values()) if combo else 0.0
    final = {k: fused[k] + (cap * combo[k] / top_combo if top_combo > 0 else 0.0) for k in fused}
    return sorted(fused, key=lambda k: (final[k], k), reverse=True)


def status() -> dict[str, Any]:
    """可用性巡检（供 /governance/status；切 bge-reranker 后探模型是否已下载）。"""
    return {
        "model": settings.BGE_RERANKER,
        "available": True,
        "detail": "RRF主序+四特征精排在线（bge-reranker P1 替换点）",
        "weights": {
            "rrf": 1.0,
            "bm25": settings.RERANK_W_BM25,
            "kw": settings.RERANK_W_KW,
            "vec": settings.RERANK_W_VEC,
            "title_bonus": settings.RERANK_TITLE_BONUS,
        },
    }
