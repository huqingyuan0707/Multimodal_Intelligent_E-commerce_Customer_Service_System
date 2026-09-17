"""问答轮次落库半段（会话归位→幂等→agent 行→挂起→审计，对齐 API 规范 §4.2/§5）

链路：run/stream 开轮 → _begin_turn（会话归位→上下文装配→幂等落库→
      重放 short-circuit）→ 生成（chat_generation）→ _persist_agent_turn
     （agent 行 + 规则表挂起 + 成本审计 + 会话刷新 + commit）；
      无据走 _persist_reject（拒答同样落行、可回放）。
红线：落库 guard 额外带 degraded/empty/rejected 标记（规则表累计连续
      降级/未解决）；handoff 判定统一交 handoff_service.auto_handoff。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.user_context import CurrentUser
from app.services import context_service, handoff_service, rag_governance, session_service
from app.services.chat_stream import loads_dict, loads_list
from app.services.vision_service import sanitize_inspections


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
            # 重放不重跑模型与工具：tool_calls 给空数组（帧形稳定），溯源走同一 trace_id 查 tool_calls 表
            replay = {
                "answer": saved.content,
                "references": loads_list(saved.citations),
                "guard": loads_dict(saved.guard),
                "faithfulness": saved.faithfulness if saved.faithfulness is not None else 0.0,
                "model": "replay",
                "degraded": False,
                "trace_id": saved.trace_id,
                "vision": loads_list(saved.attachments),
                "need_human": False,
                "context": history_ctx,
                "session_id": session.id,
                "tool_calls": [],
                "orchestration": {"notes": ["重放命中：未重跑工具调用，可按 trace_id 回查审计"]},
                "handoff": handoff_service.blank_handoff(session),
                "message_id": saved.id,
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
    tool_calls: list[dict[str, object]] | None = None,
    notes: list[str] | None = None,
    empty: bool = False,
    approval: bool = False,
) -> dict[str, object]:
    """agent 行落库 + 规则表挂起判定 + 成本审计 + 会话刷新 + commit，返回 run_text_turn 同形 result。

    tool_calls/orchestration 原样透出（本步不新落库：逐步审计已由 executor 写 tool_calls 表，
    同一 trace_id 可回查），前端 ToolCallCard 与非流式响应共用同一形状。
    落库 guard 额外带 degraded/empty 标记（规则表据此算「连续降级 / 连续未解决」）。
    """
    stored_guard = {**dict(guard), "degraded": bool(degraded), "empty": bool(empty)}
    agent_row = await session_service.save_agent_message(
        db,
        tenant=user.tenant,
        session_id=session.id,
        content=text,
        citations=[dict(r) for r in refs],
        guard=stored_guard,
        faithfulness=faith,
        trace_id=trace_id,
        client_msg_id=key,
        attachments=vision,
    )
    # C 步自动挂起：判据逐条定义在 handoff_rules 规则表，已认领/已解决不抢
    handoff = await handoff_service.auto_handoff(
        db,
        tenant=user.tenant,
        session_id=session.id,
        current_guard=stored_guard,
        exclude_client_msg_id=key,
        signals={
            "query": query,
            "vision_need_human": need_human,
            "tool_empty": bool(empty),
            "approval_pending": bool(approval),
        },
    )
    result: dict[str, object] = {
        "answer": text,
        "references": refs,
        "guard": stored_guard,
        "faithfulness": faith,
        "model": model,
        "degraded": degraded,
        "trace_id": trace_id,
        "usage": usage,
        "vision": vision,
        "need_human": need_human,
        "context": history_ctx,
        "tool_calls": list(tool_calls or []),
        "orchestration": {"notes": list(notes or [])},
        "handoff": handoff,
        # 赞踩反馈定位键（mining/feedback 的 message_id，落库行 id，刷新/重放同键）
        "message_id": agent_row.id,
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
    query: str = "",
) -> dict[str, object]:
    """无据拒答落库（run/stream 共用）：拒答话术同样落 agent 行、可回放。

    guard 落 rejected 标记（规则表据此累计「连续未解决」）；挂起同样交规则表判定。
    """
    trace = uuid.uuid4().hex[:16]
    stored_guard: dict[str, object] = {"pass": True, "rejected": True}
    reject_row = await session_service.save_agent_message(
        db,
        tenant=user.tenant,
        session_id=session.id,
        content=reason,
        citations=[],
        guard=stored_guard,
        faithfulness=0.0,
        trace_id=trace,
        client_msg_id=key,
        attachments=vision,
    )
    # C 步自动挂起：规则表判定（无据拒答 + 喊人工/情绪/连续不懂可能叠加）
    handoff = await handoff_service.auto_handoff(
        db,
        tenant=user.tenant,
        session_id=session.id,
        current_guard=stored_guard,
        exclude_client_msg_id=key,
        signals={"query": query, "no_evidence": True},
    )
    await session_service.touch_session(
        db, tenant=user.tenant, username=user.username, session_id=session.id
    )
    await db.commit()
    return {
        "answer": reason,
        "references": [],
        "guard": stored_guard,
        "faithfulness": 0.0,
        "model": "template",
        "degraded": False,
        "trace_id": trace,
        "vision": vision,
        "need_human": any(bool(v.get("need_human")) for v in vision),
        "context": history_ctx,
        "session_id": session.id,
        "tool_calls": [],
        "orchestration": {"notes": ["无据拒答：未产出可引用资料，已转人工"]},
        "handoff": handoff,
        "message_id": reject_row.id,
        "replayed": False,
        "rejected": True,
    }


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
