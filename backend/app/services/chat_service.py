"""问答编排（RAG 生成段：检索 → 本地大模型作答 → 降级，对齐 RAG 规范 §4 + ADR-0001）

链路：access_context 取租户 → knowledge_service.retrieve（db 双路链：租户/密级/生效期治理）
       → 无据抛 NoEvidenceError(2001)
       → 有据交 llm_service（本地 Ollama qwen2.5）依据资料作答
       → 模型不可用 → fallback_answer() 片段摘要降级，**绝不 500**。
稳定性口径：函数签名与拒答码 2001 不变；出参新增 model / degraded 两字段（API 规范 §4.2 已同步），
            前端不识别也能正常渲染（只读 answer/references）。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.observability import record
from app.core.user_context import CurrentUser, access_context
from app.services import knowledge_service, llm_service, session_service

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
            "content": (f"【资料】\n{blocks}\n\n【问题】{query[:500]}\n请只依据上面资料作答。"),
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


async def answer(
    query: str, db: AsyncSession | None = None, roles: list[str] | None = None
) -> dict[str, object]:
    """问答主入口，返回 {answer, references, guard, faithfulness, model, degraded, trace_id}。

    db 有值走 DB 双路链（租户/密级/生效期治理）；db=None 走历史种子路径（离线兼容）。
    """
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex[:16]
    ctx = access_context()
    refs = await knowledge_service.retrieve(query, ctx["tenant"], db=db, roles=roles)
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


def stream_id_for(client_msg_id: str | None) -> str:
    """SSE 事件 id 前缀：由幂等键确定性派生，重放产出相同 id，前端天然去重。

    无键（旧客户端）则随机，本轮内去重、跨轮不保证。
    """
    key = (client_msg_id or "").strip()
    if not key:
        return uuid.uuid4().hex[:8]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def chunk_text(text: str, size: int | None = None) -> list[str]:
    """message 事件分片（增量渲染粒度，长度走 Settings.SSE_CHUNK_CHARS）。"""
    width = size if size and size > 0 else settings.SSE_CHUNK_CHARS
    if width <= 0:
        width = 120
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def _loads_list(raw: str) -> list[dict[str, object]]:
    """回放解析：citations JSON 文本 → 引用列表，坏数据兜底空列表不断流。"""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return []
    return [dict(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _loads_dict(raw: str) -> dict[str, object]:
    """回放解析：guard JSON 文本 → 字典，坏数据兜底通过不断流。"""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return {"pass": True}
    return dict(data) if isinstance(data, dict) else {"pass": True}


async def run_text_turn(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    thread_id: str | None = None,
    client_msg_id: str = "",
) -> dict[str, object]:
    """文本轮次（含落库，对齐 API 规范 §4.2/§5）：会话归位 → 用户消息幂等落库 →
    有已存助手回复则重放（不再调模型）→ 否则 answer() 生成并落库 → commit。

    无据拒答不抛异常，以 rejected=True 随结果返回（端点转 2001/流式照常发完四帧）。
    返回 answer() 同形结果 + session_id/replayed/rejected，前端 done 原样透传。
    """
    session, _ = await session_service.ensure_session(
        db, tenant=user.tenant, username=user.username, thread_id=thread_id, title_hint=query
    )
    key = (client_msg_id or "").strip()
    if key:
        saved = await session_service.find_agent_message(
            db, session_id=session.id, client_msg_id=key
        )
        if saved is not None:
            await db.commit()
            return {
                "answer": saved.content,
                "references": _loads_list(saved.citations),
                "guard": _loads_dict(saved.guard),
                "faithfulness": saved.faithfulness if saved.faithfulness is not None else 0.0,
                "model": "replay",
                "degraded": False,
                "trace_id": saved.trace_id,
                "session_id": session.id,
                "replayed": True,
                "rejected": False,
            }
        if (
            await session_service.find_user_message(db, session_id=session.id, client_msg_id=key)
            is None
        ):
            await session_service.save_user_message(
                db, tenant=user.tenant, session_id=session.id, content=query, client_msg_id=key
            )
    else:
        await session_service.save_user_message(
            db, tenant=user.tenant, session_id=session.id, content=query
        )
    try:
        result = await answer(query, db=db, roles=user.roles)
    except NoEvidenceError as exc:
        trace = uuid.uuid4().hex[:16]
        await session_service.save_agent_message(
            db,
            tenant=user.tenant,
            session_id=session.id,
            content=str(exc),
            citations=[],
            guard={"pass": True},
            faithfulness=0.0,
            trace_id=trace,
            client_msg_id=key,
        )
        await db.commit()
        return {
            "answer": str(exc),
            "references": [],
            "guard": {"pass": True},
            "faithfulness": 0.0,
            "model": "template",
            "degraded": False,
            "trace_id": trace,
            "session_id": session.id,
            "replayed": False,
            "rejected": True,
        }
    refs_raw = result["references"]
    guard_raw = result["guard"]
    await session_service.save_agent_message(
        db,
        tenant=user.tenant,
        session_id=session.id,
        content=str(result["answer"]),
        citations=[dict(r) for r in refs_raw] if isinstance(refs_raw, list) else [],
        guard=dict(guard_raw) if isinstance(guard_raw, dict) else {"pass": True},
        faithfulness=float(result["faithfulness"])
        if isinstance(result["faithfulness"], (int, float))
        else 0.0,
        trace_id=str(result["trace_id"]),
        client_msg_id=key,
    )
    await db.commit()
    return {**result, "session_id": session.id, "replayed": False, "rejected": False}
