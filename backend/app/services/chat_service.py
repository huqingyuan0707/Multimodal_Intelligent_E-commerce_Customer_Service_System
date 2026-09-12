"""问答编排（纯函数，对齐 RAG 规范 §4 生成与可观测）

链路：access_context 取租户 → knowledge.retrieve → 有据组装/无据拒答 → record()。
LLM 接入后仅替换 _compose 内部实现，签名与拒答码 2001 不变。
"""

from __future__ import annotations

import time
import uuid

from app.core.observability import record
from app.core.user_context import access_context
from app.services import knowledge_service


class NoEvidence(Exception):
    """无据拒答（端点转 fail(ErrorCode.NO_EVIDENCE, 中文话术, 200)）。"""


def _compose(query: str, refs: list[dict[str, object]]) -> str:
    """有据组装：逐条引用标题 + 摘要，不编造引用之外的单号与政策。"""
    lines = ["根据以下店内政策为你说明："]
    for i, ref in enumerate(refs, 1):
        content = str(ref["content"])
        lines.append(f"[{i}]《{ref['title']}》：{content[:120]}")
    lines.append("如需人工跟进，可直接回复“转人工”。")
    _ = query
    return "\n".join(lines)


async def answer(query: str) -> dict[str, object]:
    """问答主入口，返回 {answer, references, guard, faithfulness, trace_id}。"""
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex[:16]
    ctx = access_context()
    refs = await knowledge_service.retrieve(query, ctx["tenant"])
    if not refs:
        record("chat", {"trace_id": trace_id, "refs": 0, "reject": True})
        raise NoEvidence("这个问题我暂时没查到权威政策，已为你转人工")
    result = {
        "answer": _compose(query, refs),
        "references": refs,
        "guard": {"pass": True},
        "faithfulness": 1.0,
        "trace_id": trace_id,
    }
    record(
        "chat",
        {
            "trace_id": trace_id,
            "refs": len(refs),
            "faithfulness": 1.0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return result
