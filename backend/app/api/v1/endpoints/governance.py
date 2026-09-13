"""治理与可观测端点框架（状态巡检，对齐 RAG 规范 §5/数据模型 §3）

链路：GET /governance/status → 适配层 status()；用量走 observability.record()。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.responses import ok
from app.services import llm_service

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/status")
async def status() -> dict[str, Any]:
    """适配层可用性巡检：大模型走真实 probe()，向量/关键词/重排待接。"""
    llm = await llm_service.probe()
    data: dict[str, Any] = {
        "llm": llm,
        "vector": "stub",
        "keyword": "stub",
        "reranker": "stub",
    }
    msg = "模型服务在线" if llm.get("available") else "模型服务不可用，问答将降级为片段摘要"
    return ok(data, msg)
