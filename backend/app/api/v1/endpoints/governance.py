"""治理与可观测端点（13 步巡检，对齐 RAG 规范 §5/数据模型 §3）

链路：GET /governance/status → 向量/关键词/重排/LLM/VLM/ASR/缓存 七适配层 status()；
      POST /governance/track → 前端行为埋点（发送/上传/播放/引用/转人工/赞踩）→ observability。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.core import cache
from app.core.observability import record
from app.core.rbac import get_current_user
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.services import llm_service, rerank_service, speech_service, vector_store, vision_service

router = APIRouter(prefix="/governance", tags=["governance"])


class TrackRequest(BaseModel):
    """埋点入参（端点私有 DTO）：事件名 ≤64 字，载荷截 500 字，绝不存原文敏感内容。"""

    event: str
    data: dict[str, Any] = {}


@router.post("/track")
async def track(
    payload: TrackRequest, user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    """前端行为埋点：只进 observability 事件流（JSONL + 计数器），不落业务表、不抛错。

    红线：埋点永远成功（200）——埋点失败不能影响买家操作；路由级登录（随 governance router）。
    """
    record(
        "frontend.track",
        {
            "event": payload.event.strip()[:64],
            "tenant": user.tenant,
            "username": user.username,
            "payload": {k: str(v)[:80] for k, v in list(payload.data.items())[:8]},
        },
    )
    return ok({"tracked": True}, "埋点已记录")


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
        "keyword": {"backend": "bm25-stdlib", "available": True},
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
            "bm25_k1": settings.BM25_K1,
            "bm25_b": settings.BM25_B,
            "rerank_w": {
                "rrf": 1.0,
                "bm25": settings.RERANK_W_BM25,
                "kw": settings.RERANK_W_KW,
                "vec": settings.RERANK_W_VEC,
                "title_bonus": settings.RERANK_TITLE_BONUS,
            },
            "rag_cache_ttl": settings.RAG_CACHE_TTL,
            "vlm_confidence": settings.VLM_CONFIDENCE_THRESHOLD,
            "asr_confidence": settings.ASR_CONFIDENCE_THRESHOLD,
        },
        "hot_fields": list(settings._HOT_FIELDS),
    }
    msg = "模型服务在线" if llm.get("available") else "模型服务不可用，问答将降级为片段摘要"
    return ok(data, msg)
