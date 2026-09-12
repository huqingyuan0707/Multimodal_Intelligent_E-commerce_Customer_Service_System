"""可观测记录占位（关键链路 _record 用，对齐 RAG 规范 §4）

链路：问答/任务 → _record() → observability.record() → Prometheus/Langfuse。
"""

from __future__ import annotations

from typing import Any


def record(event: str, fields: dict[str, Any] | None = None) -> None:
    """框架占位，不阻塞主流程，具体上报后续补。"""
    _ = (event, fields or {})
    return None
