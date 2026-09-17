"""问答编排（RAG 生成段 8-12 步，对齐 RAG 规范 §4 + ADR-0001）

链路：access_context 取租户 → retrieve（三路召回+治理，trace）→ 无据 2001
      → build_messages（拼接预算）→ llm_service 生成/降级 → validate 引用校验
      → 落库（messages+cost+audit）→ SSE done。
红线：每步 trace_step 带 tenant/trace_id；模型不可用降级绝不 500。
分层：生成半段下沉 chat_generation，落库半段下沉 chat_turn_store；
      本模块只留 run/stream 轮次编排 + 历史导入口径薄转发。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.observability import record
from app.core.user_context import CurrentUser, access_context
from app.services import knowledge_service as knowledge_service  # 兼容：单测经本模块桩检索
from app.services import llm_service, rag_governance
from app.services.chat_generation import (
    NoEvidenceError,
    _assemble_generation,
    _finalize_turn,
    answer,
)
from app.services.chat_prompt import (
    build_messages,
    faithfulness,
    fallback_answer,
    validate_references,
)
from app.services.chat_stream import chunk_text, loads_dict, loads_list, stream_id_for
from app.services.chat_turn_store import (
    _begin_turn,
    _persist_agent_turn,
    _persist_reject,
)
from app.services.vision_service import build_vision_context, sanitize_inspections

# 兼容：传输件/提示词/校验已下沉 chat_stream/chat_prompt，本模块薄转发（端点/历史测试导入口径不变）。
_loads_list = loads_list
_loads_dict = loads_dict

__all__ = [
    "NoEvidenceError",
    "answer",
    "build_messages",
    "build_vision_context",
    "chunk_text",
    "faithfulness",
    "fallback_answer",
    "run_text_turn",
    "sanitize_inspections",
    "stream_id_for",
    "stream_text_turn",
    "validate_references",
]


async def run_text_turn(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    thread_id: str | None = None,
    client_msg_id: str = "",
    inspections: list[dict[str, object]] | None = None,
    image_ids: list[str] | None = None,
) -> dict[str, object]:
    """文本/图文轮次（含落库，对齐 API 规范 §4.2/§5）：会话归位 → 上下文装配 →
    幂等落库 → 重放 short-circuit → answer 生成 → 引用校验 → 落库 + 活跃刷新。

    上下文（三层之 Context）：本轮落库前取历史窗口（不含本轮，避免自重复），
    满窗则刷新摘要；窗口 + 摘要拼 history 进 LLM 解指代，用量透给 done.context。
    图文轮 inspections 经清洗后拼上下文 + 随 agent 行 attachments 持久化；
    image_ids 存 user 行 attachments（回放可溯源）。无据拒答不抛异常。
    """
    begun = await _begin_turn(
        db,
        user=user,
        query=query,
        thread_id=thread_id,
        client_msg_id=client_msg_id,
        inspections=inspections,
        image_ids=image_ids,
    )
    if begun["replay"] is not None:
        return begun["replay"]
    session = begun["session"]
    vision = begun["vision"]
    history_block = str(begun["history_block"])
    history_ctx = dict(begun["history_ctx"])
    key = str(begun["key"])
    try:
        result = await answer(
            query,
            db=db,
            roles=user.roles,
            inspections=vision,
            history=history_block,
            context=history_ctx,
            user=user,
            session_id=session.id,
        )
    except NoEvidenceError as exc:
        return await _persist_reject(
            db,
            user=user,
            session=session,
            vision=vision,
            key=key,
            history_ctx=history_ctx,
            reason=str(exc),
            query=query,
        )
    refs_raw = result["references"]
    guard_raw = result["guard"]
    usage_raw = result.get("usage")
    calls_raw = result.get("tool_calls")
    orch_raw = result.get("orchestration")
    orch_map = orch_raw if isinstance(orch_raw, dict) else {}
    return await _persist_agent_turn(
        db,
        user=user,
        session=session,
        vision=vision,
        key=key,
        history_ctx=history_ctx,
        query=query,
        text=str(result["answer"]),
        refs=[dict(r) for r in refs_raw] if isinstance(refs_raw, list) else [],
        guard=dict(guard_raw) if isinstance(guard_raw, dict) else {"pass": True},
        faith=float(result["faithfulness"])
        if isinstance(result["faithfulness"], (int, float))
        else 0.0,
        model=str(result.get("model", "template")),
        degraded=bool(result.get("degraded", False)),
        usage=dict(usage_raw) if isinstance(usage_raw, dict) else {},
        trace_id=str(result["trace_id"]),
        need_human=bool(result.get("need_human", False)),
        tool_calls=[dict(c) for c in calls_raw] if isinstance(calls_raw, list) else [],
        notes=list(orch_map.get("notes") or []) if isinstance(orch_map.get("notes"), list) else [],
        empty=bool(orch_map.get("empty")),
        approval=bool(orch_map.get("approval")),
        rulebot=bool(result.get("rulebot", False)),
    )


async def stream_text_turn(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    thread_id: str | None = None,
    client_msg_id: str = "",
    inspections: list[dict[str, object]] | None = None,
    image_ids: list[str] | None = None,
) -> AsyncIterator[str | dict[str, object]]:
    """流式轮次（/chat/stream 与 /agent/chat/stream 共用）：与 run_text_turn 同语义同落库，
    唯一区别是生成阶段 token 增量外吐（首字不等全文拼完）。

    产出协议：先 yield 0..n 个非空 str 文本增量，最后 yield 一个 dict 终态 result
    （run_text_turn 同形，answer 为全文；端点据此组 done 帧）。无据拒答 / 重放命中时
    整段一次 yield（沿用 chunk_text 切片，帧形与旧行为一致）。校验与落库仍在全文到齐后，
    引用/落库/done 三方一致。
    流中途模型中断（已有增量）：后缀明示中断并按降级落库，保证 done 必达不断流。
    """
    begun = await _begin_turn(
        db,
        user=user,
        query=query,
        thread_id=thread_id,
        client_msg_id=client_msg_id,
        inspections=inspections,
        image_ids=image_ids,
    )
    if begun["replay"] is not None:
        replay = begun["replay"]
        for part in chunk_text(str(replay["answer"])):
            if part:
                yield part
        yield replay
        return
    session = begun["session"]
    vision = begun["vision"]
    history_block = str(begun["history_block"])
    history_ctx = dict(begun["history_ctx"])
    key = str(begun["key"])
    try:
        asm = await _assemble_generation(
            query,
            db=db,
            roles=user.roles,
            vision=vision,
            history_block=history_block,
            user=user,
            session_id=session.id,
        )
    except NoEvidenceError as exc:
        result = await _persist_reject(
            db,
            user=user,
            session=session,
            vision=vision,
            key=key,
            history_ctx=history_ctx,
            reason=str(exc),
            query=query,
        )
        yield str(exc)
        yield result
        return
    refs = asm["refs"]
    need_human = bool(asm["need_human"])
    trace_id = str(asm["trace_id"])
    messages = asm["messages"]
    vision_block = str(asm["vision_block"])
    ctx = access_context()
    started = time.perf_counter()
    degraded = False
    rulebot = False
    model = settings.LLM_MODEL
    usage: dict[str, int] = {}
    buf: list[str] = []
    try:
        async for delta in llm_service.acomplete_stream(messages):
            buf.append(delta)
            yield delta
        text = "".join(buf).strip()
        if not text:
            raise llm_service.LlmUnavailableError("模型流全程无增量，按不可用处理")
        rag_governance.trace_step(
            "llm.generate", tenant=ctx["tenant"], trace_id=trace_id, extra={"model": model}
        )
    except llm_service.LlmUnavailableError as exc:
        if buf:
            text = "".join(buf).strip() + "\n（后续内容生成中断，可重试或转人工继续跟进）"
        else:
            # FR-5 第三级：无增量即按非流式同口径切规则机器人（组装不出回落静态模板）
            from app.services import rulebot_service

            text, rulebot = rulebot_service.answer_or_fallback(
                query,
                refs=refs,
                tool_block=str(asm.get("tool_block") or ""),
                failures=[
                    dict(item) for item in asm.get("failures") or [] if isinstance(item, dict)
                ],
                vision_block=vision_block,
            )
            if rulebot:
                record("agent.rulebot", {"tenant": ctx["tenant"], "trace_id": trace_id})
            yield text
        degraded = True
        model = "template"
        rag_governance.trace_step(
            "llm.degraded",
            tenant=ctx["tenant"],
            trace_id=trace_id,
            extra={"reason": str(exc)[:120], "rulebot": rulebot},
        )
        record(
            "chat",
            {"trace_id": trace_id, "llm_degraded": str(exc)[:200], "rulebot": rulebot},
        )
    checked = _finalize_turn(
        text,
        refs,
        degraded=degraded,
        rulebot=rulebot,
        model=model,
        usage=usage,
        trace_id=trace_id,
        vision=vision,
        need_human=need_human,
        context=history_ctx,
        started=started,
        tool_calls=asm["tool_calls"],
        notes=asm["notes"],
        empty=bool(asm["empty"]),
        approval=bool(asm["approval"]),
    )
    result = await _persist_agent_turn(
        db,
        user=user,
        session=session,
        vision=vision,
        key=key,
        history_ctx=history_ctx,
        query=query,
        text=str(checked["answer"]),
        refs=refs,
        guard=checked["guard"] if isinstance(checked["guard"], dict) else {"pass": True},
        faith=float(checked["faithfulness"])
        if isinstance(checked["faithfulness"], (int, float))
        else 0.0,
        model=str(checked.get("model", "template")),
        degraded=bool(checked.get("degraded", False)),
        usage={},
        trace_id=str(checked["trace_id"]),
        need_human=bool(checked.get("need_human", False)),
        tool_calls=list(asm["tool_calls"]),
        notes=list(asm["notes"]),
        rulebot=bool(checked.get("rulebot", False)),
    )
    yield result
