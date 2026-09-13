"""重排适配层（检索第 6 步 Rerank，对齐 RAG 规范 §2）

链路：RRF 融合分 → 本模块 rerank（RRF 主序 + 向量余弦 + 关键词破平局）
      → knowledge_service 做多样性裁剪。
红线：P0 纯 Python（bge-reranker P1 替换 rerank 体即可）；status() 供治理巡检。
"""

from __future__ import annotations

from typing import Any

from app.config import settings


def rerank(
    fused: dict[str, float],
    cosine: dict[str, float] | None = None,
    keyword: dict[str, float] | None = None,
) -> list[str]:
    """分数重排：RRF 主序，向量余弦次之，关键词再次之（纯函数可单测）。"""
    cos = cosine or {}
    kw = keyword or {}
    return sorted(
        fused,
        key=lambda k: (fused[k], cos.get(k, 0.0), kw.get(k, 0.0)),
        reverse=True,
    )


def status() -> dict[str, Any]:
    """可用性巡检（供 /governance/status；切 bge-reranker 后探模型是否已下载）。"""
    return {
        "model": settings.BGE_RERANKER,
        "available": True,
        "detail": "RRF+余弦本地重排在线（bge-reranker P1 替换点）",
    }
