"""工具执行器（超时 30s + 幂等重试 3 次 + 熔断 + 全量审计，对齐 FRDv2 FR-5 与附录 A）

链路：policy.ensure_allowed 放行 → 参数 Schema 校验 → 熔断闸门
      → asyncio.wait_for(handler, 超时) → 失败按幂等性重试 → 落 tool_calls 审计 → 返回结果。
失败分级（关键口径，避免把正常业务结果当故障熔断）：
- BusinessError（订单不存在/状态非法/无据等）：业务拒绝，**不重试、不计熔断**，原码上抛；
- TimeoutError / 其他异常（依赖抖动）：**计熔断失败**，幂等工具线性退避重试到上限。
红线：非幂等工具恒只调一次（重复退款/重复发券的资损口子）；熔断开闸直接 4007 快失败；
      好/坏两条路径都必须写 tool_calls（工具调用透明可回放）。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record
from app.core.user_context import current_on_behalf_of
from app.db.models import ToolCall
from app.modules.agent import policy, registry
from app.modules.agent.contracts import ToolContext, ToolSpec, validate_args


@dataclass
class _Breaker:
    """单工具熔断状态（进程内，按工具名隔离）。"""

    failures: int = 0
    opened_at: float = 0.0
    last_error: str = ""
    history: list[int] = field(default_factory=list)  # 最近若干次耗时，供前端画趋势


_breakers: dict[str, _Breaker] = {}
_breaker_lock = threading.Lock()
_HISTORY_MAX = 10


# ---------------- 熔断闸门 ----------------


def _breaker_of(name: str) -> _Breaker:
    """惰性建熔断位（无锁读优先，双检写入）。"""
    state = _breakers.get(name)
    if state is None:
        with _breaker_lock:
            state = _breakers.setdefault(name, _Breaker())
    return state


def is_open(name: str) -> bool:
    """是否处于开闸（含半开复位：冷却到点自动清闸放行一次试探）。"""
    state = _breakers.get(name)
    if state is None or not state.opened_at:
        return False
    cooldown = float(settings.AGENT_TOOL_CIRCUIT_COOLDOWN_SECONDS)
    if time.monotonic() - state.opened_at >= cooldown:
        with _breaker_lock:
            state.opened_at = 0.0
            state.failures = 0
        return False
    return True


def _record_success(name: str, latency_ms: int) -> None:
    """成功：清失败计数并追加耗时历史。"""
    state = _breaker_of(name)
    with _breaker_lock:
        state.failures = 0
        state.opened_at = 0.0
        state.last_error = ""
        state.history.append(latency_ms)
        del state.history[:-_HISTORY_MAX]


def _record_failure(name: str, error: str) -> None:
    """失败：累加计数，达阈值即开闸（记录开闸时刻用于冷却计时）。"""
    state = _breaker_of(name)
    with _breaker_lock:
        state.failures += 1
        state.last_error = error[:200]
        if state.failures >= int(settings.AGENT_TOOL_CIRCUIT_THRESHOLD) and not state.opened_at:
            state.opened_at = time.monotonic()


def breaker_snapshot(name: str) -> dict[str, Any]:
    """单工具熔断快照（注册中心端点透出，运维可观测）。"""
    state = _breakers.get(name)
    if state is None:
        return {
            "failures": 0,
            "open": False,
            "last_error": "",
            "recent_latency_ms": [],
        }
    return {
        "failures": state.failures,
        "open": is_open(name),
        "last_error": state.last_error,
        "recent_latency_ms": list(state.history),
    }


def reset_breakers(name: str = "") -> None:
    """复位熔断（运维手动恢复 / 测试隔离）；name 空=全复位。"""
    with _breaker_lock:
        if name:
            _breakers.pop(name, None)
            return
        _breakers.clear()


# ---------------- 审计 ----------------


async def _audit(
    ctx: ToolContext,
    *,
    name: str,
    args: dict[str, Any],
    result: dict[str, Any],
    latency_ms: int,
    trace_id: str,
) -> None:
    """落 tool_calls 审计（只 flush 不 commit，由调用方统一提交，保证与业务同事务）。

    on_behalf_of 从请求上下文取（服务账号入口写入），外部 Agent 调用时做到
    「调用方 + 发起人」两列可查，审计链不断在系统边界。
    """
    ctx.db.add(
        ToolCall(
            trace_id=trace_id or ctx.trace_id,
            tenant=ctx.tenant,
            username=ctx.username,
            on_behalf_of=current_on_behalf_of(),
            name=name,
            args=json.dumps(args, ensure_ascii=False, default=str)[:4000],
            result=json.dumps(result, ensure_ascii=False, default=str)[:4000],
            latency_ms=latency_ms,
        )
    )
    await ctx.db.flush()


async def _audit_failure(
    ctx: ToolContext, *, name: str, args: dict[str, Any], message: str, trace_id: str
) -> None:
    """失败同样留痕（被拒/超时/熔断都要能在审计里查到）。"""
    await _audit(
        ctx,
        name=name,
        args=args,
        result={"status": "failed", "message": message},
        latency_ms=0,
        trace_id=trace_id,
    )


# ---------------- 调用主链 ----------------


def _outcome(
    spec: ToolSpec,
    *,
    result: dict[str, Any],
    args: dict[str, Any],
    attempts: int,
    latency_ms: int,
    trace_id: str,
) -> dict[str, Any]:
    """成功出参（端点/runtime 共用同一形状，前端 ToolCallCard 直接渲染）。"""
    approval_id = str(result.get("approval_id") or "")
    return {
        "tool": spec.name,
        "status": "ok",
        "scope": spec.scope,
        "idempotent": spec.idempotent,
        "requires_approval": spec.requires_approval,
        "approval_required": bool(spec.requires_approval),
        "approval_id": approval_id,
        "args": args,
        "result": result,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "timeout_seconds": registry.timeout_of(spec),
        "trace_id": trace_id,
    }


async def _invoke_once(ctx: ToolContext, spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """单次调用（超时由 Settings 控制，阻塞型 handler 自行走 to_thread）。"""
    timeout = registry.timeout_of(spec)
    return await asyncio.wait_for(spec.handler(ctx, args), timeout=timeout)


async def _invoke_with_retry(
    ctx: ToolContext, spec: ToolSpec, args: dict[str, Any], started: float
) -> tuple[dict[str, Any] | None, int, ErrorCode | None]:
    """重试主循环：返回 (结果, 尝试次数, 失败码)。

    成功时失败码为 None；尝试耗尽返回 None + 失败码（超时给 4002、其余依赖失败给 4008），
    调用方据此抛错并落审计，避免「超时」和「上游挂了」在错误码上糊成同一个。
    """
    max_attempts = registry.retries_of(spec) + 1
    attempts = 0
    code: ErrorCode | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            result = await _invoke_once(ctx, spec, args)
            _record_success(spec.name, int((time.perf_counter() - started) * 1000))
            return result, attempts, None
        except BusinessError:
            # 业务拒绝：不是依赖故障，原码上抛（重试与熔断都不该介入）
            raise
        except TimeoutError:
            reason = f"工具 {spec.name} 超时（>{registry.timeout_of(spec)}s）"
            code = ErrorCode.TASK_TIMEOUT
        except Exception as exc:  # 依赖异常统一收敛为可重试失败（业务拒绝已在上分支上抛）
            reason = f"工具 {spec.name} 调用失败：{str(exc)[:120]}"
            code = ErrorCode.TOOL_CALL_FAILED
        _record_failure(spec.name, reason)
        if attempts >= max_attempts:
            return None, attempts, code
        await asyncio.sleep(float(settings.AGENT_TOOL_RETRY_BACKOFF_SECONDS) * attempts)
    return None, attempts, code


async def call(
    ctx: ToolContext, *, name: str, args: dict[str, Any] | None = None, trace_id: str = ""
) -> dict[str, Any]:
    """工具调用唯一入口：策略 → 校验 → 熔断 → 执行 → 审计。

    失败一律抛 BusinessError（由 main.py 收口成 fail() 信封），端点不再写 try/except。
    """
    spec = registry.get(name)
    payload = dict(args or {})
    trace = trace_id or ctx.trace_id
    # 策略先行：Scope 不命中直接 403，绝不"没权限也执行"
    policy.ensure_allowed(roles=ctx.roles, spec=spec, args=payload)
    errors = validate_args(spec.params, payload)
    if errors:
        message = "；".join(errors)
        await _audit_failure(ctx, name=spec.name, args=payload, message=message, trace_id=trace)
        raise BusinessError(ErrorCode.PARAM_INVALID, message)
    if is_open(spec.name):
        message = f"工具 {spec.name} 连续失败已熔断，请稍后重试或转人工跟进"
        await _audit_failure(ctx, name=spec.name, args=payload, message=message, trace_id=trace)
        raise BusinessError(ErrorCode.TOOL_CIRCUIT_OPEN, message, 503)

    started = time.perf_counter()
    result, attempts, code = await _invoke_with_retry(ctx, spec, payload, started)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if result is None:
        reason = _breakers.get(spec.name, _Breaker()).last_error or f"工具 {spec.name} 调用失败"
        await _audit_failure(ctx, name=spec.name, args=payload, message=reason, trace_id=trace)
        record("agent.tool", {"tool": spec.name, "ok": False, "latency_ms": latency_ms})
        raise BusinessError(code or ErrorCode.TOOL_CALL_FAILED, f"{reason}；已尝试 {attempts} 次")

    data = _outcome(
        spec, result=result, args=payload, attempts=attempts, latency_ms=latency_ms, trace_id=trace
    )
    await _audit(
        ctx,
        name=spec.name,
        args=payload,
        result=data,
        latency_ms=latency_ms,
        trace_id=trace,
    )
    record(
        "agent.tool",
        {
            "tool": spec.name,
            "ok": True,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "approval": data["approval_required"],
            "trace_id": trace,
        },
    )
    return data
