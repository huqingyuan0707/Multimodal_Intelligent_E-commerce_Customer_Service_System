"""问答编排（RAG 生成段：检索 → 本地大模型作答 → 降级，对齐 RAG 规范 §4 + ADR-0001）

链路：access_context 取租户 → knowledge_service.retrieve → 无据抛 NoEvidenceError(2001)
      → 有据交 llm_service（本地 Ollama qwen2.5）依据资料作答
      → 模型不可用 → fallback_answer() 片段摘要降级，**绝不 500**。
稳定性口径：函数签名与拒答码 2001 不变；出参新增 model / degraded 两字段（API 规范 §4.2 已同步），
            前端不识别也能正常渲染（只读 answer/references）。
"""

from __future__ import annotations

import re
import time
import uuid

from app.config import settings
from app.core.observability import record
from app.core.user_context import access_context
from app.services import knowledge_service, llm_service

# 提示词硬约束：宁可不答不可答错（换模型不改这里）
_SYSTEM_PROMPT = (
    "你是电商店铺的在线客服，代表商家回答买家问题。必须遵守："
    "1) 只依据【资料】作答，资料里没有的价格、尺码、面料、发货时限、快递单号、政策一律不得编造；"
    "2) 资料不足以回答时，直接说明「这点资料里没有，我帮你转人工确认」，不要猜测；"
    "3) 用简体中文，简洁分点，引用来源时在句末标注编号，例如 [1]。"
)

_CITED = re.compile(r"\[(\d{1,2})\]")


class NoEvidenceError(Exception):
    """无据拒答（端点转 fail(ErrorCode.NO_EVIDENCE, 中文话术, 200)）。"""


def build_messages(query: str, refs: list[dict[str, object]]) -> list[dict[str, str]]:
    """拼提示词：资料按 [n] 编号注入（单条按 LLM_REF_CHARS 截断，控制本地模型上下文压力）。"""
    blocks = "\n".join(
        f"[{i}]《{ref.get('title', '')}》{str(ref.get('content', ''))[: settings.LLM_REF_CHARS]}"
        for i, ref in enumerate(refs, 1)
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"【资料】\n{blocks}\n\n【问题】{query[:500]}\n请只依据上面资料作答。"
            ),
        },
    ]


def fallback_answer(query: str, refs: list[dict[str, object]]) -> str:
    """降级回复（模型不可用时）：逐条列资料摘要，不编造引用之外的单号与政策。"""
    lines = ["已为你找到相关的店内政策（以下为知识库原文摘要）："]
    for i, ref in enumerate(refs, 1):
        lines.append(f"[{i}]《{ref.get('title', '')}》：{str(ref.get('content', ''))[:120]}")
    lines.append("如需人工跟进，可直接回复“转人工”。")
    _ = query
    return "\n".join(lines)


def faithfulness(text: str, ref_count: int) -> float:
    """忠实度：答案自报的引用编号必须都落在实际资料范围内，越界按比例扣分（疑似编造）。"""
    cited = {int(num) for num in _CITED.findall(text)}
    if not cited:
        return 0.9
    valid = set(range(1, ref_count + 1))
    return round(len(cited & valid) / len(cited), 2)


async def answer(query: str) -> dict[str, object]:
    """问答主入口，返回 {answer, references, guard, faithfulness, model, degraded, trace_id}。"""
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex[:16]
    ctx = access_context()
    refs = await knowledge_service.retrieve(query, ctx["tenant"])
    if not refs:
        record("chat", {"trace_id": trace_id, "refs": 0, "reject": True})
        raise NoEvidenceError("这个问题我暂时没查到权威政策，已为你转人工")

    degraded = False
    model = "template"
    try:
        reply = await llm_service.complete(build_messages(query, refs))
        text, model = reply.text, reply.model
    except llm_service.LlmUnavailableError as exc:
        degraded = True
        text = fallback_answer(query, refs)
        record("chat", {"trace_id": trace_id, "llm_degraded": str(exc)[:200]})
    faith = faithfulness(text, len(refs))

    result: dict[str, object] = {
        "answer": text,
        "references": refs,
        "guard": {"pass": True, "degraded": degraded},
        "faithfulness": faith,
        "model": model,
        "degraded": degraded,
        "trace_id": trace_id,
    }
    record(
        "chat",
        {
            "trace_id": trace_id,
            "refs": len(refs),
            "faithfulness": faith,
            "model": model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return result
