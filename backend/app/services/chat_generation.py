"""问答生成半段（编排/检索→拼接→生成→校验，对齐 RAG 规范 §4 + ADR-0001）

链路：answer 入口 → sanitize 清洗 → _assemble_generation（守卫→编排/
      回落直调→无据抛错→拼提示词）→ llm_service 生成/降级 →
      _finalize_turn（引用校验→guard/faith→结果字典，不落库）。
红线：每步 trace_step 带 tenant/trace_id；模型不可用降级绝不 500；
      落库归 chat_turn_store，本模块无 DB 写。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.observability import record
from app.core.user_context import CurrentUser, access_context
from app.modules.agent import runtime as agent_runtime
from app.services import guard_service, knowledge_service, llm_service, rag_governance
from app.services.chat_prompt import (
    build_messages,
    fallback_answer,
    validate_references,
)
from app.services.vision_service import build_vision_context, sanitize_inspections


class NoEvidenceError(Exception):
    """无据拒答（端点转 fail(ErrorCode.NO_EVIDENCE, 中文话术, 200)）。"""


async def _assemble_generation(
    query: str,
    *,
    db: AsyncSession | None,
    roles: list[str] | None,
    vision: list[dict[str, object]],
    history_block: str,
    user: CurrentUser | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """生成前半（answer 与 stream_text_turn 共用）：编排/检索 → 无据抛错 → 拼提示词。

    检索段优先走 Agent 编排（plan → executor → 连接器，对齐执行步骤 B 余项①接线）：
    产出引用 + 业务工具事实 + 编排说明，done 透出 tool_calls（前端 ToolCallCard 直接渲染）；
    编排不可用（缺 user/db、开关关闭、内部异常）时回落 knowledge_service.retrieve 直调，
    两条路治理口径一致（租户/密级/生效期/渠道过滤都在 knowledge_service 内）。
    vision 为已清洗的 inspections；返回 messages/refs/need_human/trace_id/vision_block/tool_calls/notes。
    无据（引用与业务事实皆空）时与 answer 原逻辑一致记 trace + 直接抛 NoEvidenceError。
    """
    trace_id = uuid.uuid4().hex[:16]
    ctx = access_context()
    vision_block = build_vision_context(vision)
    need_human = any(bool(v.get("need_human")) for v in vision)
    # 第一道闸：输入域守卫（注入/域外直接拒答转人工，不烧检索与模型；GUARD_ENABLED 可旁路）
    guard = guard_service.check(query)
    if guard["refuse"]:
        rag_governance.trace_step(
            "guard.reject",
            tenant=ctx["tenant"],
            trace_id=trace_id,
            extra={"category": guard["category"]},
        )
        record("chat", {"trace_id": trace_id, "guard_reject": guard["category"]})
        raise NoEvidenceError(str(guard["reason"]))
    refs: list[dict[str, object]] = []
    tool_calls: list[dict[str, object]] = []
    notes: list[str] = []
    tool_block = ""
    orch = await _orchestrate(db, user=user, query=query, session_id=session_id, trace_id=trace_id)
    if orch is None:
        notes = ["编排不可用，已回落直连检索"]
        refs = await knowledge_service.retrieve(
            query, ctx["tenant"], db=db, roles=roles, trace_id=trace_id
        )
    else:
        refs = list(orch["refs"])
        tool_calls = list(orch["tool_calls"])
        notes = list(orch["notes"])
        tool_block = str(orch["tool_block"])
    if not refs and not tool_block:
        rag_governance.trace_step(
            "rag.reject", tenant=ctx["tenant"], trace_id=trace_id, extra={"refs": 0}
        )
        record("chat", {"trace_id": trace_id, "refs": 0, "reject": True})
        raise NoEvidenceError("这个问题我暂时没查到权威政策，已为你转人工")
    if need_human:
        rag_governance.trace_step(
            "vlm.human", tenant=ctx["tenant"], trace_id=trace_id, extra={"vision": len(vision)}
        )
    messages = build_messages(
        query,
        refs,
        vision_block,
        history_block,
        tool_block,
        system_override=await _online_system(db, tenant=ctx["tenant"]),
    )
    return {
        "messages": messages,
        "refs": refs,
        "need_human": need_human,
        "trace_id": trace_id,
        "vision_block": vision_block,
        "tool_calls": tool_calls,
        "notes": notes,
        # 转人工规则表信号（C 步）：工具空手而归 / 敏感动作已送审 —— 落库时交给 handoff_rules 判定
        "empty": bool(orch["empty"]) if orch is not None else False,
        "approval": bool(orch["approval"]) if orch is not None else False,
    }


async def _online_system(db: AsyncSession | None, *, tenant: str) -> str:
    """Studio 线上 Prompt 正文（发布即对话生效；无版本/db 缺失/异常即 "" 走代码常量回退）。

    函数内延迟 import studio_service：模块顶层互引会成环（studio 评测复用脚本，
    脚本又调 chat_service）；调用时各模块早已加载完毕。单行查询失败绝不拖垮对话。
    """
    if db is None:
        return ""
    try:
        from app.services import studio_service

        return await studio_service.get_online_system(db, tenant=tenant)
    except Exception:
        return ""


async def _orchestrate(
    db: AsyncSession | None,
    *,
    user: CurrentUser | None,
    query: str,
    session_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    """编排尝试：条件不足或内部异常一律返回 None（调用方回落直调，绝不拖垮对话）。"""
    if user is None or db is None or not settings.AGENT_CHAT_ORCHESTRATE:
        return None
    try:
        return await agent_runtime.orchestrate(
            db, user=user, query=query, session_id=session_id, trace_id=trace_id
        )
    except Exception as exc:
        # 编排是「加分项」不是「必经路」：任何意外都回落直调，并把原因留在 trace 里可查
        rag_governance.trace_step(
            "agent.degraded",
            tenant=user.tenant,
            trace_id=trace_id,
            extra={"reason": str(exc)[:120]},
        )
        record("chat", {"trace_id": trace_id, "agent_degraded": str(exc)[:200]})
        return None


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
    tool_calls: list[dict[str, object]] | None = None,
    notes: list[str] | None = None,
    empty: bool = False,
    approval: bool = False,
) -> dict[str, object]:
    """生成后半（answer 与 stream_text_turn 共用）：引用校验 → guard/faith → 结果字典。

    不落库（落库归 chat_turn_store）；started 为 answer 起始 perf_counter。
    empty/approval 是转人工规则表信号（工具空手 / 敏感送审），随 orchestration 透到落库段。
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
        "tool_calls": list(tool_calls or []),
        "orchestration": {
            "notes": list(notes or []),
            "empty": bool(empty),
            "approval": bool(approval),
        },
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
    user: CurrentUser | None = None,
    session_id: str = "",
) -> dict[str, object]:
    """问答主入口，返回 {answer, references, guard, faithfulness, model, degraded, trace_id, usage,
    vision, need_human, context, tool_calls, orchestration}。

    db 有值走 DB 三路链（租户/密级/生效期/渠道治理）；db=None 走历史种子路径。
    图文轮 inspections 拼进提示词（定级+方案+时效），need_human 透给端点转人工卡。
    多轮 history（context_service 已裁剪/清洗）拼进提示词解指代；context 原样透给 done。
    每步 trace_step 带 tenant/trace_id；引用校验不通过记 guard.pass=False（进 Mining）。
    """
    started = time.perf_counter()
    vision = sanitize_inspections(inspections or [], settings.IMAGE_MAX_COUNT)
    asm = await _assemble_generation(
        query,
        db=db,
        roles=roles,
        vision=vision,
        history_block=history,
        user=user,
        session_id=session_id,
    )
    refs = asm["refs"]
    need_human = bool(asm["need_human"])
    trace_id = str(asm["trace_id"])
    messages = asm["messages"]
    vision_block = str(asm["vision_block"])
    tool_calls = asm["tool_calls"]
    notes = asm["notes"]
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
        text = fallback_answer(query, refs, vision_block)
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
        tool_calls=tool_calls,
        notes=notes,
    )
