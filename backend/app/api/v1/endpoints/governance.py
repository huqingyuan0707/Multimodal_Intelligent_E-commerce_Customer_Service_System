"""治理与可观测端点（13 步巡检，对齐 RAG 规范 §5/数据模型 §3）

链路：GET /governance/status → 向量/关键词/重排/LLM/VLM/ASR/缓存 七适配层 status()。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.core import cache
from app.core.responses import ok
from app.services import llm_service, rerank_service, speech_service, vector_store, vision_service

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/status")
async def status() -> dict[str, Any]:
    """七层巡检：向量+重排+VLM+ASR+缓存 走真实 status()，关键词本地恒可用，阈值全回显。"""
    llm = await llm_service.probe()
    vector = vector_store.status()
    reranker = rerank_service.status()
    vlm = await vision_service.probe()
    speech = await speech_service.probe()
    data: dict[str, Any] = {
        "llm": llm,
        "vector": vector,
        "keyword": {"backend": "tfidf-stdlib", "available": True},
        "reranker": reranker,
        "vlm": vlm,
        "speech": speech,
        "cache": cache.status(),
        "thresholds": {
            "top_k": settings.TOP_K,
            "rrf_k": settings.RRF_K,
            "db_threshold": settings.RAG_DB_THRESHOLD,
            "diversity_per_doc": settings.RAG_DIVERSITY_PER_DOC,
            "faithfulness_warn": settings.FAITHFULNESS_WARN,
            "vlm_confidence": settings.VLM_CONFIDENCE_THRESHOLD,
            "asr_confidence": settings.ASR_CONFIDENCE_THRESHOLD,
        },
        "hot_fields": list(settings._HOT_FIELDS),
    }
    msg = "模型服务在线" if llm.get("available") else "模型服务不可用，问答将降级为片段摘要"
    return ok(data, msg)
