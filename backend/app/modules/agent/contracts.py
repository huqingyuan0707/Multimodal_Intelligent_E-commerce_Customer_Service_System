"""Agent 内核契约（状态机 / 工具规格 / JSON Schema 子集校验，对齐 FRDv2 FR-3、FR-5 与附录 A）

链路：registry 持 ToolSpec → policy.check 鉴权与判审批 → executor.call 执行落审计
      → runtime 推进 AgentState 并把 checkpoint 落 tasks 表。
口径：
- 工具入参用 JSON Schema 子集描述（required/type/enum/min/max/minLength/additionalProperties）；
  本项目不引三方校验库，自带精简校验器，错误信息一律中文可直接展示。
- 状态流转白名单集中在 TRANSITIONS，非法流转抛 4009，绝不静默改写状态。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode

# ---------------- 状态机（FR-3：IDLE→PLANNING→ACTING→OBSERVING→REFLECTING→DONE） ----------------


class AgentState(StrEnum):
    """Agent Runtime 状态（三分支：WAITING_APPROVAL / WAITING_HUMAN / FAILED）。"""

    IDLE = "IDLE"
    PLANNING = "PLANNING"
    ACTING = "ACTING"
    OBSERVING = "OBSERVING"
    REFLECTING = "REFLECTING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_HUMAN = "WAITING_HUMAN"
    DONE = "DONE"
    FAILED = "FAILED"


STATE_LABELS: dict[str, str] = {
    AgentState.IDLE: "空闲",
    AgentState.PLANNING: "规划中",
    AgentState.ACTING: "执行中",
    AgentState.OBSERVING: "观察中",
    AgentState.REFLECTING: "反思中",
    AgentState.WAITING_APPROVAL: "等待审批",
    AgentState.WAITING_HUMAN: "等待人工",
    AgentState.DONE: "已完成",
    AgentState.FAILED: "已失败",
}

# 终态：不再自动推进（FAILED 可经 resume 重新规划）
TERMINAL_STATES: frozenset[AgentState] = frozenset({AgentState.DONE})
# 挂起态：需外部动作（审批人/坐席）才能继续
SUSPENDED_STATES: frozenset[AgentState] = frozenset(
    {AgentState.WAITING_APPROVAL, AgentState.WAITING_HUMAN}
)

TRANSITIONS: dict[AgentState, tuple[AgentState, ...]] = {
    AgentState.IDLE: (AgentState.PLANNING, AgentState.FAILED),
    AgentState.PLANNING: (
        AgentState.ACTING,
        AgentState.WAITING_HUMAN,
        AgentState.FAILED,
    ),
    AgentState.ACTING: (
        AgentState.OBSERVING,
        AgentState.WAITING_APPROVAL,
        AgentState.WAITING_HUMAN,
        AgentState.FAILED,
    ),
    AgentState.OBSERVING: (AgentState.REFLECTING, AgentState.ACTING, AgentState.FAILED),
    AgentState.REFLECTING: (
        AgentState.ACTING,
        AgentState.DONE,
        AgentState.WAITING_HUMAN,
        AgentState.FAILED,
    ),
    # 审批/人工分支解除后可继续执行，也可直接收敛
    AgentState.WAITING_APPROVAL: (AgentState.ACTING, AgentState.DONE, AgentState.FAILED),
    AgentState.WAITING_HUMAN: (AgentState.ACTING, AgentState.DONE, AgentState.FAILED),
    AgentState.DONE: (),
    AgentState.FAILED: (AgentState.PLANNING,),
}


def state_label(state: AgentState | str) -> str:
    """状态中文化（前端直接渲染，禁止各处自造映射表）。"""
    return STATE_LABELS.get(str(state), str(state))


def can_transition(src: AgentState | str, dst: AgentState | str) -> bool:
    """流转白名单校验（未知状态一律 False，不抛错，供展示层探测用）。"""
    try:
        allowed = TRANSITIONS.get(AgentState(str(src)), ())
    except ValueError:
        return False
    return str(dst) in {str(s) for s in allowed}


def ensure_transition(src: AgentState | str, dst: AgentState | str) -> AgentState:
    """非法流转抛 4009（中文可操作），返回目标状态供链式使用。"""
    if not can_transition(src, dst):
        raise BusinessError(
            ErrorCode.AGENT_STATE_ILLEGAL,
            f"状态流转非法：{state_label(src)} → {state_label(dst)}",
        )
    return AgentState(str(dst))


# ---------------- 工具规格与执行上下文（FR-5：Schema + Scope + 幂等 + 超时重试） ----------------


@dataclass(frozen=True)
class ToolContext:
    """一次工具调用的执行上下文（租户/用户一律来自 Token，绝不取请求体）。"""

    db: AsyncSession
    tenant: str
    username: str
    roles: list[str]
    session_id: str = ""
    trace_id: str = ""


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    """工具注册项（附录 A 契约的进程内表述）。

    idempotent=False 的工具绝不自动重试（避免重复退款/重复发券）；
    requires_approval=True 表示「调用即送审」：执行体只落申请单，账不动（FR-7 恒进口径）。
    timeout_seconds / max_retries 为 None 时取 Settings 默认（禁止散落硬编码）。
    """

    name: str
    scope: str
    description: str
    params: dict[str, Any]
    handler: ToolHandler
    idempotent: bool = True
    requires_approval: bool = False
    approval_action: str = ""
    timeout_seconds: float | None = None
    max_retries: int | None = None


# ---------------- JSON Schema 子集校验（无三方依赖，中文报错） ----------------

_TYPE_NAMES: dict[str, str] = {
    "string": "字符串",
    "integer": "整数",
    "number": "数字",
    "boolean": "布尔值",
    "array": "数组",
    "object": "对象",
}


def _type_ok(value: Any, kind: str) -> bool:
    """类型判定：Python 里 bool 是 int 子类，必须显式排除（否则 true 会被当整数收下）。"""
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return True


def _check_field(name: str, schema: dict[str, Any], value: Any) -> list[str]:
    """单字段校验（类型 / 枚举 / 边界 / 长度），返回中文错误列表。"""
    label = str(schema.get("title") or schema.get("description") or name)
    kind = str(schema.get("type", ""))
    errors: list[str] = []
    if kind and not _type_ok(value, kind):
        return [f"参数「{label}」应为{_TYPE_NAMES.get(kind, kind)}"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in enum:
        return [f"参数「{label}」只能是 {'/'.join(str(e) for e in enum)}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        low, high = schema.get("minimum"), schema.get("maximum")
        if isinstance(low, (int, float)) and value < low:
            errors.append(f"参数「{label}」不得小于 {low}")
        if isinstance(high, (int, float)) and value > high:
            errors.append(f"参数「{label}」不得大于 {high}")
    if isinstance(value, str):
        low = schema.get("minLength")
        high = schema.get("maxLength")
        if isinstance(low, int) and len(value) < low:
            errors.append(f"参数「{label}」至少 {low} 个字符")
        if isinstance(high, int) and len(value) > high:
            errors.append(f"参数「{label}」最长 {high} 个字符")
    return errors


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """按 JSON Schema 子集校验入参，返回中文错误列表（空列表 = 通过）。"""
    if not isinstance(args, dict):
        return ["工具入参必须是键值对对象"]
    properties = schema.get("properties")
    props: dict[str, Any] = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    errors: list[str] = []
    for key in required if isinstance(required, list) else []:
        if key not in args or args[key] in ("", None):
            label = str(props.get(key, {}).get("title") or key)
            errors.append(f"缺少必填参数「{label}」")
    for key, value in args.items():
        spec = props.get(key)
        if not isinstance(spec, dict):
            if schema.get("additionalProperties") is False:
                errors.append(f"不支持的参数「{key}」")
            continue
        errors.extend(_check_field(key, spec, value))
    return errors
