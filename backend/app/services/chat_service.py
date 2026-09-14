"""问答编排（RAG 生成段 8-12 步，对齐 RAG 规范 §4 + ADR-0001）

链路：access_context 取租户 → retrieve（三路召回+治理，trace）→ 无据 2001
      → build_messages（拼接预算）→ llm_service 生成/降级 → validate 引用校验
      → 落库（messages+cost+audit）→ SSE done。
红线：每步 trace_step 带 tenant/trace_id；模型不可用降级绝不 500。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.observability import record
from app.core.user_context import CurrentUser, access_context
from app.services import (
    context_service,
    knowledge_service,
    llm_service,
    rag_governance,
    session_service,
    workbench_service,
)
from app.services.chat_prompt import (
    build_messages,
    faithfulness,
    fallback_answer,
    validate_references,
)
from app.services.chat_stream import chunk_text, loads_dict, loads_list, stream_id_for
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


class NoEvidenceError(Exception):
    """无据拒答（端点转 fail(ErrorCode.NO_EVIDENCE, 中文话术, 200)）。"""


# ---------------- 图文售后（FR-1.2，执行步骤 A） ----------------
# 定级/清洗收口 vision_service，提示词/校验收口 chat_prompt（阈值/方案/预算单源），
# 本模块只做编排；历史测试导入口径经 __all__ 薄转发保持不变。


async def _assemble_generation(
    query: str,
    *,
    db: AsyncSession | None,
    roles: list[str] | None,
    vision: list[dict[str, object]],
    history_block: str,
) -> dict[str, Any]:
    """生成前半（answer 与 stream_text_turn 共用）：检索 → 无据抛错 → 拼提示词。

    vision 为已清洗的 inspections；返回 messages/refs/need_human/trace_id/vision_block。
    无据时与 answer 原逻辑一致记 trace + 直接抛 NoEvidenceError。
    """
    trace_id = uuid.uuid4().hex[:16]
    ctx = access_context()
    vision_block = build_vision_context(vision)
    need_human = any(bool(v.get("need_human")) for v in vision)
    refs = await knowledge_service.retrieve(
        query, ctx["tenant"], db=db, roles=roles, trace_id=trace_id
    )
    if not refs:
        rag_governance.trace_step(
            "rag.reject", tenant=ctx["tenant"], trace_id=trace_id, extra={"refs": 0}
        )
        record("chat", {"trace_id": trace_id, "refs": 0, "reject": True})
        raise NoEvidenceError("这个问题我暂时没查到权威政策，已为你转人工")
    if need_human:
        rag_governance.trace_step(
            "vlm.human", tenant=ctx["tenant"], trace_id=trace_id, extra={"vision": len(vision)}
        )
    messages = build_messages(query, refs, vision_block, history_block)
    return {
        "messages": messages,
        "refs": refs,
        "need_human": need_human,
        "trace_id": trace_id,
        "vision_block": vision_block,
    }


def _finalize_turn(
    text: str,
    refs: list[dict[str, object]],
    *,
    degraded: bool,
    model: str,
    usage: dict[str, int],
    trace_id: str,
    vision: list[dict[str, object]],
    need_human: bool,
    context: dict[str, int] | None,
    started: float,
) -> dict[str, object]:
    """生成后半（answer 与 stream_text_turn 共用）：引用校验 → guard/faith → 结果字典。

    不落库（落库归 _persist_agent_turn）；started 为 answer 起始 perf_counter。
    """
    ctx = access_context()
    checked = validate_references(text, refs)
    raw_faith: object = checked.get("faithfulness", 0.0)
    faith = float(raw_faith) if isinstance(raw_faith, (int, float)) else 0.0
    raw_guard: object = checked.get("guard", {})
    guard_src = raw_guard if isinstance(raw_guard, dict) else {}
    guard = {"pass": bool(guard_src.get("pass")), "degraded": degraded}

    result: dict[str, object] = {
        "answer": text,
        "references": refs,
        "guard": guard,
        "faithfulness": faith,
        "model": model,
        "degraded": degraded,
        "trace_id": trace_id,
        "usage": usage,
        "vision": vision,
        "need_human": need_human,
        "context": dict(context or {"rounds": 0, "tokens": 0, "dropped": 0}),
    }
    if not guard["pass"]:
        rag_governance.trace_step(
            "mining.candidate",
            tenant=ctx["tenant"],
            trace_id=trace_id,
            extra={"faith": faith, "bad": checked["bad"]},
        )
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


async def answer(
    query: str,
    db: AsyncSession | None = None,
    roles: list[str] | None = None,
    inspections: list[dict[str, object]] | None = None,
    history: str = "",
    context: dict[str, int] | None = None,
) -> dict[str, object]:
    """问答主入口，返回 {answer, references, guard, faithfulness, model, degraded, trace_id, usage,
    vision, need_human, context}。

    db 有值走 DB 三路链（租户/密级/生效期/渠道治理）；db=None 走历史种子路径。
    图文轮 inspections 拼进提示词（定级+方案+时效），need_human 透给端点转人工卡。
    多轮 history（context_service 已裁剪/清洗）拼进提示词解指代；context 原样透给 done。
    每步 trace_step 带 tenant/trace_id；引用校验不通过记 guard.pass=False（进 Mining）。
    """
    started = time.perf_counter()
    vision = sanitize_inspections(inspections or [], settings.IMAGE_MAX_COUNT)
    asm = await _assemble_generation(
        query, db=db, roles=roles, vision=vision, history_block=history
    )
    refs = asm["refs"]
    need_human = bool(asm["need_human"])
    trace_id = str(asm["trace_id"])
    messages = asm["messages"]
    vision_block = str(asm["vision_block"])
    ctx = access_context()

    degraded = False
    model = "template"
    usage: dict[str, int] = {}
    # 低置信图文轮：不硬答，直接转人工话术（仍走 RAG 退换政策引用透出）
    try:
        reply = await llm_service.complete(messages)
        text, model, usage = reply.text, reply.model, dict(reply.usage or {})
        rag_governance.trace_step(
            "llm.generate", tenant=ctx["tenant"], trace_id=trace_id, extra={"model": model}
        )
    except llm_service.LlmUnavailableError as exc:
        degraded = True
        text = fallback_answer(query, refs, vision_block, history)
        rag_governance.trace_step(
            "llm.degraded",
            tenant=ctx["tenant"],
            trace_id=trace_id,
            extra={"reason": str(exc)[:120]},
        )
        record("chat", {"trace_id": trace_id, "llm_degraded": str(exc)[:200]})
    return _finalize_turn(
        text,
        refs,
        degraded=degraded,
        model=model,
        usage=usage,
        trace_id=trace_id,
        vision=vision,
        need_human=need_human,
        context=context,
        started=started,
    )


async def _begin_turn(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    thread_id: str | None,
    client_msg_id: str,
    inspections: list[dict[str, object]] | None,
    image_ids: list[str] | None,
) -> dict[str, Any]:
    """轮次前置（run_text_turn 与 stream_text_turn 共用）：会话归位 → 上下文装配 →
    幂等落库 → 重放 short-circuit。

    返回 {"session","vision","history_block","history_ctx","key","replay"}；
    replay 命中时为 run_text_turn 同形 result（调用方直接产出整段，不再调模型）。
    """
    session, _ = await session_service.ensure_session(
        db, tenant=user.tenant, username=user.username, thread_id=thread_id, title_hint=query
    )
    vision = sanitize_inspections(inspections or [], settings.IMAGE_MAX_COUNT)
    files = [str(f)[:64] for f in (image_ids or [])[: settings.IMAGE_MAX_COUNT] if str(f).strip()]
    user_modality = "image" if (vision or files) else "text"
    user_attachments = [{"file_id": f} for f in files]
    history_block, ctx_stats, summary = await context_service.assemble(db, session=session)
    history_ctx = {**ctx_stats, "summarized": bool(summary)}
    key = (client_msg_id or "").strip()
    if key:
        saved = await session_service.find_agent_message(
            db, session_id=session.id, client_msg_id=key
        )
        if saved is not None:
            await db.commit()
            replay = {
                "answer": saved.content,
                "references": _loads_list(saved.citations),
                "guard": _loads_dict(saved.guard),
                "faithfulness": saved.faithfulness if saved.faithfulness is not None else 0.0,
                "model": "replay",
                "degraded": False,
                "trace_id": saved.trace_id,
                "vision": _loads_list(saved.attachments),
                "need_human": False,
                "context": history_ctx,
                "session_id": session.id,
                "replayed": True,
                "rejected": False,
            }
            return {
                "session": session,
                "vision": vision,
                "history_block": history_block,
                "history_ctx": history_ctx,
                "key": key,
                "replay": replay,
            }
        if (
            await session_service.find_user_message(db, session_id=session.id, client_msg_id=key)
            is None
        ):
            await session_service.save_user_message(
                db,
                tenant=user.tenant,
                session_id=session.id,
                content=query,
                client_msg_id=key,
                modality=user_modality,
                attachments=user_attachments,
            )
    else:
        await session_service.save_user_message(
            db,
            tenant=user.tenant,
            session_id=session.id,
            content=query,
            modality=user_modality,
            attachments=user_attachments,
        )
    return {
        "session": session,
        "vision": vision,
        "history_block": history_block,
        "history_ctx": history_ctx,
        "key": key,
        "replay": None,
    }


async def _persist_agent_turn(
    db: AsyncSession,
    *,
    user: CurrentUser,
    session: Any,
    vision: list[dict[str, object]],
    key: str,
    history_ctx: dict[str, int],
    query: str,
    text: str,
    refs: list[dict[str, object]],
    guard: dict[str, object],
    faith: float,
    model: str,
    degraded: bool,
    usage: dict[str, int],
    trace_id: str,
    need_human: bool,
) -> dict[str, object]:
    """agent 行落库 + 成本审计 + 会话刷新 + commit，返回 run_text_turn 同形 result。"""
    await session_service.save_agent_message(
        db,
        tenant=user.tenant,
        session_id=session.id,
        content=text,
        citations=[dict(r) for r in refs],
        guard=dict(guard),
        faithfulness=faith,
        trace_id=trace_id,
        client_msg_id=key,
        attachments=vision,
    )
    if need_human:
        # C 步自动挂起：VLM 低置信不硬答，会话进待接队列（已认领/已解决不抢）
        await workbench_service.mark_pending_if_idle(
            db, tenant=user.tenant, session_id=session.id, reason="VLM 低置信，需人工复核"
        )
    result: dict[str, object] = {
        "answer": text,
        "references": refs,
        "guard": guard,
        "faithfulness": faith,
        "model": model,
        "degraded": degraded,
        "trace_id": trace_id,
        "usage": usage,
        "vision": vision,
        "need_human": need_human,
        "context": history_ctx,
    }
    await _record_cost_and_audit(db, user=user, session_id=session.id, result=result, query=query)
    await session_service.touch_session(
        db, tenant=user.tenant, username=user.username, session_id=session.id
    )
    await db.commit()
    return {**result, "session_id": session.id, "replayed": False, "rejected": False}


async def _persist_reject(
    db: AsyncSession,
    *,
    user: CurrentUser,
    session: Any,
    vision: list[dict[str, object]],
    key: str,
    history_ctx: dict[str, int],
    reason: str,
) -> dict[str, object]:
    """无据拒答落库（run/stream 共用）：拒答话术同样落 agent 行、可回放。"""
    trace = uuid.uuid4().hex[:16]
    await session_service.save_agent_message(
        db,
        tenant=user.tenant,
        session_id=session.id,
        content=reason,
        citations=[],
        guard={"pass": True},
        faithfulness=0.0,
        trace_id=trace,
        client_msg_id=key,
        attachments=vision,
    )
    # C 步自动挂起：无据拒答同样进待接队列（已认领/已解决不抢）
    await workbench_service.mark_pending_if_idle(
        db, tenant=user.tenant, session_id=session.id, reason="无据拒答，需人工确认"
    )
    await session_service.touch_session(
        db, tenant=user.tenant, username=user.username, session_id=session.id
    )
    await db.commit()
    return {
        "answer": reason,
        "references": [],
        "guard": {"pass": True},
        "faithfulness": 0.0,
        "model": "template",
        "degraded": False,
        "trace_id": trace,
        "vision": vision,
        "need_human": any(bool(v.get("need_human")) for v in vision),
        "context": history_ctx,
        "session_id": session.id,
        "replayed": False,
        "rejected": True,
    }


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
        )
    refs_raw = result["references"]
    guard_raw = result["guard"]
    usage_raw = result.get("usage")
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
            query, db=db, roles=user.roles, vision=vision, history_block=history_block
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
            text = fallback_answer(query, refs, vision_block, history_block)
            yield text
        degraded = True
        model = "template"
        rag_governance.trace_step(
            "llm.degraded",
            tenant=ctx["tenant"],
            trace_id=trace_id,
            extra={"reason": str(exc)[:120]},
        )
        record("chat", {"trace_id": trace_id, "llm_degraded": str(exc)[:200]})
    checked = _finalize_turn(
        text,
        refs,
        degraded=degraded,
        model=model,
        usage=usage,
        trace_id=trace_id,
        vision=vision,
        need_human=need_human,
        context=history_ctx,
        started=started,
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
    )
    yield result


async def _record_cost_and_audit(
    db: AsyncSession, *, user: CurrentUser, session_id: str, result: dict[str, object], query: str
) -> None:
    """落库第 12 步：cost_records 成本归因 + audit_logs 问答审计（同事务 flush）。

    token 无上游 usage 时走 context_service.estimate_tokens 统一估算（中文 1.5 字/token，
    与预算裁剪同源），保证看板不断流。
    """
    from app.db.models import CostRecord

    usage = result.get("usage")
    usage_map = dict(usage) if isinstance(usage, dict) else {}
    prompt_tok = int(usage_map.get("prompt_tokens", 0) or 0)
    comp_tok = int(usage_map.get("completion_tokens", 0) or 0)
    if not prompt_tok:
        prompt_tok = context_service.estimate_tokens(query + str(result.get("answer", "")))
    if not comp_tok:
        comp_tok = context_service.estimate_tokens(str(result.get("answer", "")))
    db.add(
        CostRecord(
            tenant=user.tenant,
            session_id=session_id,
            model=str(result.get("model", "template")),
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
            cost_cents=0,
        )
    )
    await db.flush()
    await rag_governance.audit_write(
        db,
        tenant=user.tenant,
        actor=user.username,
        action="chat.answer",
        target=session_id,
        detail={"trace_id": str(result.get("trace_id", "")), "faith": result.get("faithfulness")},
    )
