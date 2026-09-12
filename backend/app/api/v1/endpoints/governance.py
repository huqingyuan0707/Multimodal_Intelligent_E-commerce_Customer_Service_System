"""治理与可观测端点框架（状态巡检，对齐 RAG 规范 §5/数据模型 §3）

链路：GET /governance/status → 适配层 status()；用量走 observability.record()。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.responses import ok

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/status")
async def status() -> dict[str, object]:
    """后端健康占位（向量/关键词/重排可用性后续补）。"""
    return ok({"vector": "stub", "keyword": "stub", "reranker": "stub"}, "治理框架已就绪")
