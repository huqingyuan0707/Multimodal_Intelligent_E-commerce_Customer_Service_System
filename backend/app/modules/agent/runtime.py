"""Agent Runtime 编排内核（FRDv2 FR-3 状态机 + tasks.checkpoint 可恢复）

链路：run() IDLE→PLANNING（规则规划）→ACTING（policy→executor 逐步执行）
      →OBSERVING（收结果）→REFLECTING（判续步/收敛）→DONE；
      分支：敏感工具→WAITING_APPROVAL（挂起等审批，账不动）；无据/无可用工具→WAITING_HUMAN；
      依赖故障→FAILED。每步写 tasks.checkpoint 并提交，resume() 从断点续跑不重放已完成步。
红线：
- Runtime 不直辖业务表：只经连接器 → services，业务规则永远只有一份。
- 摘要只复述工具真实返回，检索为空绝不编造（无据即转人工，对齐 2001 拒答口径）。
- 已送审的轮次 resume 前先查审批态：仍 pending 直接 4003，不让编排绕过人工审批。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record
from app.core.user_context import CurrentUser
from app.modules.agent import executor, registry
from app.modules.agent.contracts import (
    AgentState,
    ToolContext,
    ensure_transition,
    state_label,
    validate_args,
)
from app.services import approval_service, handoff_service, task_service

RUN_TASK_TYPE = "agent.run"
# 规划规则（规则版先行：可解释、可测、无模型依赖；命中即用第一个）
PLAN_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("物流", "快递", "运单", "到哪", "签收", "几号到"), "logistics.query", "问物流进度"),
    (("退款", "退钱", "补偿", "赔付"), "refund.create", "提退款诉求（敏感，走审批）"),
    (("库存", "有货", "断码", "补货", "还剩"), "stock.query", "问库存"),
    (("优惠", "券", "满减", "活动", "折扣", "划算"), "coupon.query", "问优惠活动"),
    (("订单", "单号", "发货", "下单"), "order.query", "问订单"),
)
DEFAULT_TOOL = "kb.retrieve"


@dataclass
class PlanStep:
    """一个可执行步骤（规划产物，落进 checkpoint 可回放）。"""

    tool: str
    args: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "reason": self.reason}


def _yuan(cents: Any) -> str:
    """分转元展示（金额一律整数分存储，展示层才转元）。"""
    try:
        return f"{(int(cents) / 100):.2f} 元"
    except (TypeError, ValueError):
        return "未知金额"


def _step_of(tool: str, args: dict[str, Any], reason: str) -> PlanStep | None:
    """构造步骤：入参不齐（未通过 Schema）就不产出步骤，避免带残参硬调。"""
    spec = registry.maybe_get(tool)
    if spec is None:
        return None
    payload = dict(args)
    if tool == DEFAULT_TOOL and not payload.get("query"):
        return None
    if validate_args(spec.params, payload):
        return None
    return PlanStep(tool=tool, args=payload, reason=reason)


def plan(query: str, tool_args: dict[str, Any] | None = None) -> dict[str, Any]:
    """规则规划：关键词命中取工具，参数不足或未命中回落知识库检索。

    返回 {"steps": [...], "notes": [中文说明]}；notes 会一并透给前端展示，
    让「为什么走了这条路」可见（避免黑箱编排）。
    """
    text = (query or "").strip()
    provided = dict(tool_args or {})
    notes: list[str] = []
    steps: list[PlanStep] = []
    for keywords, tool, why in PLAN_RULES:
        if not any(word in text for word in keywords):
            continue
        step = _step_of(tool, provided, why)
        if step is not None:
            steps.append(step)
        else:
            notes.append(f"命中「{why}」但缺少必填参数（如订单号/SKU），已回落知识库检索")
        break
    if not steps:
        fallback_args = {"query": text} if text else {}
        step = _step_of(DEFAULT_TOOL, fallback_args, "走知识库检索")
        if step is not None:
            steps.append(step)
        else:
            notes.append("问题为空或无法解析，未产出可执行步骤")
    return {"steps": steps[: settings.AGENT_MAX_STEPS], "notes": notes}


def _is_empty(tool: str, result: dict[str, Any]) -> bool:
    """结果是否「空手而归」：空手即转人工，绝不拿空结果硬答。"""
    if tool == "kb.retrieve":
        return int(result.get("total", 0)) == 0
    if tool == "coupon.query":
        return int(result.get("total", 0)) == 0
    if tool == "stock.query":
        return int(result.get("warehouse_count", 0)) == 0
    return False


def summarize(tool: str, args: dict[str, Any], result: dict[str, Any]) -> str:
    """把工具真实返回翻成中文一句话（只复述，不加戏、不编造节点与时效）。"""
    if tool == "order.query":
        return (
            f"订单 {result.get('outer_id', '')} 当前为「{result.get('status_label', '')}」，"
            f"金额 {_yuan(result.get('total'))}。"
        )
    if tool == "logistics.query":
        return (
            f"物流单号 {result.get('tracking_no', '')}（{result.get('company', '')}）"
            f"当前状态「{result.get('status_label', '')}」，轨迹节点对接后补齐。"
        )
    if tool == "stock.query":
        size = str(result.get("size", "") or "").strip() or "全部尺码"
        return f"{size} 可用库存 {result.get('available', 0)} 件。"
    if tool == "coupon.query":
        return f"当前有 {result.get('total', 0)} 个进行中的优惠活动。"
    if tool == "kb.retrieve":
        refs = result.get("references") or []
        if not refs:
            return "知识库未检索到权威依据，已转人工确认。"
        titles = "、".join(str(ref.get("title", "")) for ref in refs[:3])
        return f"已检索到 {result.get('total', 0)} 条政策依据：{titles}。"
    if tool == "refund.create":
        return (
            f"已提交退款申请（金额 {_yuan(args.get('amount'))}），"
            f"进入审批后由人工确认，账目暂未变动。"
        )
    return f"工具 {tool} 执行完成。"


def _now_text() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


async def _persist(
    db: AsyncSession, *, tenant: str, task_id: str, checkpoint: dict[str, Any]
) -> None:
    """每步落 checkpoint 并提交（崩溃后可 resume，这是「步骤持久化」的落地口径）。"""
    checkpoint["updated_at"] = _now_text()
    await task_service.save_checkpoint(db, tenant=tenant, task_id=task_id, checkpoint=checkpoint)
    await db.commit()


def _advance(checkpoint: dict[str, Any], dst: AgentState) -> None:
    """推进状态（非法流转抛 4009，绝不静默改写）。"""
    checkpoint["state"] = str(ensure_transition(checkpoint.get("state", AgentState.IDLE), dst))


async def _apply_approval_state(
    db: AsyncSession, *, tenant: str, checkpoint: dict[str, Any]
) -> str:
    """resume 前先看审批结果：pending 不放行（4003），驳回则终止本轮。"""
    approval_id = str(checkpoint.get("approval_id") or "")
    if not approval_id:
        return ""
    row = await approval_service.get_or_raise(db, tenant, approval_id)
    if row.status == "pending":
        raise BusinessError(
            ErrorCode.APPROVAL_REQUIRED, "该轮已提交审批，请等审批通过后再继续推进", 409
        )
    if row.status == "rejected":
        checkpoint["error"] = {
            "code": int(ErrorCode.APPROVAL_DENIED),
            "message": "审批已驳回，本轮终止",
        }
        return "rejected"
    return "approved"


def _make_ctx(
    db: AsyncSession, *, user: CurrentUser, checkpoint: dict[str, Any], trace_id: str
) -> ToolContext:
    return ToolContext(
        db=db,
        tenant=user.tenant,
        username=user.username,
        roles=list(user.roles),
        session_id=str(checkpoint.get("session_id") or ""),
        trace_id=trace_id,
    )


async def _run_step(
    db: AsyncSession,
    *,
    user: CurrentUser,
    checkpoint: dict[str, Any],
    index: int,
    trace_id: str,
) -> dict[str, Any]:
    """执行单步：ACTING（调用）→ 审批/观察 → 结果并入 checkpoint。"""
    ctx = _make_ctx(db, user=user, checkpoint=checkpoint, trace_id=trace_id)
    step = dict(checkpoint["steps"][index])
    _advance(checkpoint, AgentState.ACTING)
    await _persist(db, tenant=user.tenant, task_id=checkpoint["task_id"], checkpoint=checkpoint)
    outcome = await executor.call(
        ctx, name=str(step["tool"]), args=dict(step.get("args") or {}), trace_id=trace_id
    )
    checkpoint["results"].append(outcome)
    checkpoint["cursor"] = index + 1
    if outcome["approval_required"]:
        checkpoint["approval_id"] = outcome.get("approval_id", "")
        _advance(checkpoint, AgentState.WAITING_APPROVAL)
        await _persist(db, tenant=user.tenant, task_id=checkpoint["task_id"], checkpoint=checkpoint)
        return outcome
    _advance(checkpoint, AgentState.OBSERVING)
    _advance(checkpoint, AgentState.REFLECTING)
    await _persist(db, tenant=user.tenant, task_id=checkpoint["task_id"], checkpoint=checkpoint)
    return outcome


def _answer_of(checkpoint: dict[str, Any]) -> str:
    """汇总所有成功步骤的中文摘要（多步按序拼接，不合并改写）。"""
    lines: list[str] = []
    for step, outcome in zip(checkpoint["steps"], checkpoint["results"], strict=False):
        lines.append(summarize(str(step["tool"]), dict(step.get("args") or {}), outcome["result"]))
    return "".join(lines)


async def _settle(
    db: AsyncSession,
    *,
    user: CurrentUser,
    checkpoint: dict[str, Any],
    state: AgentState,
) -> dict[str, Any]:
    """收敛：落终态 + 同步任务状态 + 需人工时挂起会话，返回对外结果。"""
    _advance(checkpoint, state)
    await _persist(db, tenant=user.tenant, task_id=checkpoint["task_id"], checkpoint=checkpoint)
    if state == AgentState.WAITING_HUMAN and checkpoint.get("session_id"):
        # 转人工判据统一走规则表（C 步）：编排空手只是其中一条，可与喊人工/情绪/连续不懂叠加
        await handoff_service.auto_handoff(
            db,
            tenant=user.tenant,
            session_id=str(checkpoint["session_id"]),
            signals={"query": str(checkpoint.get("query") or ""), "agent_no_result": True},
        )
        await db.commit()
    await task_service.mark_task(
        db,
        tenant=user.tenant,
        task_id=checkpoint["task_id"],
        status="done" if state == AgentState.DONE else "running",
        progress=1.0 if state == AgentState.DONE else 0.5,
        output={
            "state": str(state),
            "answer": _answer_of(checkpoint),
            "steps": checkpoint["steps"],
        },
        error=str((checkpoint.get("error") or {}).get("message", "")),
    )
    record(
        "agent.run",
        {
            "task_id": checkpoint["task_id"],
            "state": str(state),
            "steps": len(checkpoint["results"]),
            "trace_id": checkpoint["trace_id"],
        },
    )
    return snapshot_of(checkpoint)


def snapshot_of(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """编排快照（端点 GET /agent/runtime/{id} 与 run/resume 同形出参）。"""
    state = str(checkpoint.get("state", AgentState.IDLE))
    return {
        "task_id": checkpoint.get("task_id", ""),
        "state": state,
        "state_label": state_label(state),
        "query": checkpoint.get("query", ""),
        "session_id": checkpoint.get("session_id", ""),
        "cursor": int(checkpoint.get("cursor", 0)),
        "steps": checkpoint.get("steps", []),
        "results": checkpoint.get("results", []),
        "notes": checkpoint.get("notes", []),
        "answer": _answer_of(checkpoint),
        "approval_id": checkpoint.get("approval_id", ""),
        "error": checkpoint.get("error", {}),
        "trace_id": checkpoint.get("trace_id", ""),
        "updated_at": checkpoint.get("updated_at", ""),
    }


async def _drive(
    db: AsyncSession,
    *,
    user: CurrentUser,
    checkpoint: dict[str, Any],
    trace_id: str,
) -> dict[str, Any]:
    """推进主循环（run 与 resume 共用）：从 cursor 续跑剩余步骤并收敛。"""
    steps = checkpoint["steps"]
    while int(checkpoint["cursor"]) < len(steps):
        index = int(checkpoint["cursor"])
        try:
            outcome = await _run_step(
                db, user=user, checkpoint=checkpoint, index=index, trace_id=trace_id
            )
        except BusinessError as exc:
            checkpoint["error"] = {"code": int(exc.code), "message": exc.msg}
            await _settle(db, user=user, checkpoint=checkpoint, state=AgentState.FAILED)
            if exc.code == ErrorCode.TOOL_SCOPE_DENIED:
                raise  # 权限问题必须显式暴露（403），但任务态已落 FAILED，不留假 running
            return snapshot_of(checkpoint)
        if outcome["approval_required"]:
            return snapshot_of(checkpoint)
        if _is_empty(str(checkpoint["steps"][index]["tool"]), outcome["result"]):
            checkpoint["notes"].append("工具未返回可用结果，转人工确认")
            return await _settle(
                db, user=user, checkpoint=checkpoint, state=AgentState.WAITING_HUMAN
            )
    return await _settle(db, user=user, checkpoint=checkpoint, state=AgentState.DONE)


async def run(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    session_id: str = "",
    tool_args: dict[str, Any] | None = None,
    trace_id: str = "",
) -> dict[str, Any]:
    """跑一轮编排：建任务行 → 规划 → 逐步执行 → 收敛（每步 checkpoint 落盘）。"""
    trace = trace_id or uuid.uuid4().hex[:16]
    planned = plan(query, tool_args)
    row = await task_service.create_task(
        db,
        tenant=user.tenant,
        username=user.username,
        type=RUN_TASK_TYPE,
        payload={"query": query, "session_id": session_id, "trace_id": trace},
    )
    checkpoint: dict[str, Any] = {
        "task_id": row.id,
        "state": str(AgentState.IDLE),
        "query": query,
        "session_id": session_id,
        "cursor": 0,
        "steps": [step.to_dict() for step in planned["steps"]],
        "results": [],
        "notes": list(planned["notes"]),
        "approval_id": "",
        "error": {},
        "trace_id": trace,
    }
    await task_service.mark_task(
        db, tenant=user.tenant, task_id=row.id, status="running", progress=0.1
    )
    _advance(checkpoint, AgentState.PLANNING)
    await _persist(db, tenant=user.tenant, task_id=row.id, checkpoint=checkpoint)
    if not checkpoint["steps"]:
        return await _settle(db, user=user, checkpoint=checkpoint, state=AgentState.WAITING_HUMAN)
    return await _drive(db, user=user, checkpoint=checkpoint, trace_id=trace)


KB_CHAT_SCOPE = "kb:read"
"""对话链的知识库检索 scope：任何能进对话的主体都隐式具备（与接线前直调口径一致）。"""


async def orchestrate(
    db: AsyncSession,
    *,
    user: CurrentUser,
    query: str,
    session_id: str = "",
    tool_args: dict[str, Any] | None = None,
    trace_id: str = "",
) -> dict[str, Any] | None:
    """对话主链编排入口（`/chat` 与 `/chat/stream` 的检索段，对齐执行步骤 B 余项①「接线」）。

    与 run() 的分工（刻意不同，不是重复实现）：
    - 复用同一套 plan + executor.call：规划规则、Scope 校验、幂等、超时/重试/熔断、tool_calls 审计只有一份；
    - 不建 tasks 行、不落 checkpoint：对话轮次的「可恢复」由 approvals（敏感动作）与
      client_msg_id 幂等（断线重放）承担 —— 否则每条买家消息都会在任务中心刷一条 agent.run；
    - 敏感工具不自动触发：requires_approval 的工具要凑齐必填参数才会被规划出，主链不传 tool_args 时，
      买家一句「我要退款」只会回落知识库检索，绝不自动生成资金审批单；
    - 工具业务拒绝（订单不存在/无权调用）不外抛：转成一条 rejected 结果交生成段据实说明，
      整轮仍走既有降级链路（对齐「外部服务不可用绝不返回 500」）。

    返回 {"refs","tool_calls","notes","tool_block","approval","empty","trace_id"}：
    refs 直接喂 build_messages/validate_references；tool_calls 直接透给 done（前端 ToolCallCard）；
    tool_block 是拼给 LLM 的业务事实块。
    **返回 None = 编排内核未装载**（bootstrap 失败 / 单测未注册连接器）：由调用方回落直连检索，
    绝不把「工具没装上」放大成「无据拒答」。
    """
    if registry.maybe_get(DEFAULT_TOOL) is None:
        return None
    trace = trace_id or uuid.uuid4().hex[:16]
    planned = plan(query, tool_args)
    notes = list(planned.get("notes") or [])
    refs: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    facts: list[str] = []
    approval: dict[str, Any] = {}
    empty = False
    # 对话链固有能力：知识库检索对任何能进对话的主体都开放（与接线前直调口径一致）；
    # 其余工具严格按 Token 角色判 Scope —— 绝不在对话链里替买家放开业务权限。
    ctx = ToolContext(
        db=db,
        tenant=user.tenant,
        username=user.username,
        roles=list(dict.fromkeys([*user.roles, KB_CHAT_SCOPE])),
        session_id=session_id,
        trace_id=trace,
    )
    for step in planned.get("steps") or []:
        args = dict(step.args)
        try:
            outcome = await executor.call(ctx, name=step.tool, args=args, trace_id=trace)
        except BusinessError as exc:
            code = int(exc.code)
            if code == int(ErrorCode.TOOL_SCOPE_DENIED):
                notes.append(f"当前身份无权调用 {step.tool}，已回落知识库检索")
                continue
            tool_calls.append(
                {
                    "tool": step.tool,
                    "status": "rejected",
                    "code": code,
                    "message": str(exc),
                    "args": args,
                    "result": {},
                    "approval_required": False,
                    "approval_id": "",
                    "attempts": 0,
                    "latency_ms": 0,
                    "trace_id": trace,
                }
            )
            notes.append(f"{step.tool} 未成功：{exc}")
            continue
        tool_calls.append(outcome)
        if outcome.get("approval_required"):
            approval = outcome
            notes.append("该动作需人工审批，已生成审批单（账目未变动）")
            break
        payload = outcome.get("result")
        result = dict(payload) if isinstance(payload, dict) else {}
        if step.tool == DEFAULT_TOOL:
            refs = [item for item in result.get("references") or [] if isinstance(item, dict)]
            continue
        if _is_empty(step.tool, result):
            empty = True
            notes.append(f"{step.tool} 未返回可用结果，已转人工跟进")
            continue
        fact = summarize(step.tool, args, result)
        if fact:
            facts.append(fact)
    record(
        "agent.orchestrate",
        {
            "trace_id": trace,
            "tools": [str(item.get("tool", "")) for item in tool_calls],
            "refs": len(refs),
            "approval": bool(approval),
            "empty": empty,
        },
    )
    return {
        "refs": refs,
        "tool_calls": tool_calls,
        "notes": notes,
        "tool_block": "\n".join(facts),
        "approval": approval,
        "empty": empty,
        "trace_id": trace,
    }


async def snapshot(db: AsyncSession, *, tenant: str, task_id: str) -> dict[str, Any]:
    """查编排快照（跨租户 404；无 checkpoint 说明不是 Runtime 任务）。"""
    row = await task_service.get_task(db, tenant=tenant, task_id=task_id)
    checkpoint = task_service.checkpoint_of(row)
    if not checkpoint:
        raise BusinessError(ErrorCode.TASK_NOT_FOUND, "该任务不是 Agent 编排任务，无检查点", 404)
    return snapshot_of(checkpoint)


async def resume(
    db: AsyncSession, *, user: CurrentUser, task_id: str, trace_id: str = ""
) -> dict[str, Any]:
    """从检查点续跑：审批未决先拦（4003），驳回直接终止，通过后继续剩余步骤。"""
    row = await task_service.get_task(db, tenant=user.tenant, task_id=task_id)
    checkpoint = task_service.checkpoint_of(row)
    if not checkpoint:
        raise BusinessError(ErrorCode.TASK_NOT_FOUND, "该任务不是 Agent 编排任务，无检查点", 404)
    trace = trace_id or str(checkpoint.get("trace_id") or uuid.uuid4().hex[:16])
    checkpoint["trace_id"] = trace
    verdict = await _apply_approval_state(db, tenant=user.tenant, checkpoint=checkpoint)
    if verdict == "rejected":
        return await _settle(db, user=user, checkpoint=checkpoint, state=AgentState.FAILED)
    if str(checkpoint.get("state")) == str(AgentState.DONE):
        return snapshot_of(checkpoint)
    if int(checkpoint["cursor"]) >= len(checkpoint["steps"]):
        return await _settle(db, user=user, checkpoint=checkpoint, state=AgentState.DONE)
    return await _drive(db, user=user, checkpoint=checkpoint, trace_id=trace)
