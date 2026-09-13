"""问答编排（RAG 生成段 8-12 步，对齐 RAG 规范 §4 + ADR-0001）

链路：access_context 取租户 → retrieve（三路召回+治理，trace）→ 无据 2001
      → build_messages（拼接预算）→ llm_service 生成/降级 → validate 引用校验
      → 落库（messages+cost+audit）→ SSE done。
红线：每步 trace_step 带 tenant/trace_id；模型不可用降级绝不 500。
"""

from __future__ import annotations

import time
import uuid

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
    "validate_references",
]


class NoEvidenceError(Exception):
    """无据拒答（端点转 fail(ErrorCode.NO_EVIDENCE, 中文话术, 200)）。"""


# ---------------- 图文售后（FR-1.2，执行步骤 A） ----------------
# 定级/清洗收口 vision_service，提示词/校验收口 chat_prompt（阈值/方案/预算单源），
# 本模块只做编排；历史测试导入口径经 __all__ 薄转发保持不变。


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
    trace_id = uuid.uuid4().hex[:16]
    ctx = access_context()
    vision = sanitize_inspections(inspections or [], settings.IMAGE_MAX_COUNT)
    need_human = any(bool(v.get("need_human")) for v in vision)
    vision_block = build_vision_context(vision)
    refs = await knowledge_service.retrieve(
        query, ctx["tenant"], db=db, roles=roles, trace_id=trace_id
    )
    if not refs:
        rag_governance.trace_step(
            "rag.reject", tenant=ctx["tenant"], trace_id=trace_id, extra={"refs": 0}
        )
        record("chat", {"trace_id": trace_id, "refs": 0, "reject": True})
        raise NoEvidenceError("这个问题我暂时没查到权威政策，已为你转人工")

    degraded = False
    model = "template"
    usage: dict[str, int] = {}
    # 低置信图文轮：不硬答，直接转人工话术（仍走 RAG 退换政策引用透出）
    if need_human:
        rag_governance.trace_step(
            "vlm.human", tenant=ctx["tenant"], trace_id=trace_id, extra={"vision": len(vision)}
        )
    try:
        reply = await llm_service.complete(build_messages(query, refs, vision_block, history))
        text, model, usage = reply.text, reply.model, dict(reply.usage or {})
        rag_governance.trace_step(
            "llm.generate", tenant=ctx["tenant"], trace_id=trace_id, extra={"model": model}
        )
    except llm_service.LlmUnavailableError as exc:
        degraded = True
        text = fallback_answer(query, refs, vision_block, history)
        rag_governance.trace_step(
            "llm.degraded", tenant=ctx["tenant"], trace_id=trace_id, extra={"reason": str(exc)[:120]}
        )
        record("chat", {"trace_id": trace_id, "llm_degraded": str(exc)[:200]})
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
            return {
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
    try:
        result = await answer(
            query, db=db, roles=user.roles, inspections=vision,
            history=history_block, context=history_ctx,
        )
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
            attachments=vision,
        )
        await session_service.touch_session(
            db, tenant=user.tenant, username=user.username, session_id=session.id
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
            "vision": vision,
            "need_human": any(bool(v.get("need_human")) for v in vision),
            "context": history_ctx,
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
        attachments=vision,
    )
    await _record_cost_and_audit(
        db, user=user, session_id=session.id, result=result, query=query
    )
    await session_service.touch_session(
        db, tenant=user.tenant, username=user.username, session_id=session.id
    )
    await db.commit()
    return {**result, "session_id": session.id, "replayed": False, "rejected": False}





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
