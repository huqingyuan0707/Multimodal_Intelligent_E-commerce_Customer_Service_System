"""工具策略引擎（对齐 FRDv2 FR-5 Scope 鉴权 + FR-7 敏感动作恒进审批）

链路：executor.call / runtime 执行前必过 check() → {"allowed","approval_required","reason"}。
红线：
- Scope 不命中直接拒（4006），绝不「没权限也执行」；角色即权限，`*` 通配。
- refund.create 等敏感工具 requires_approval=True：调用即落审批单，账不动，
  阈值以下的退款同样送审（FR-7「退款恒进审批」口径，不走金额分支）。
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import BusinessError, ErrorCode
from app.core.governance import has_scope
from app.modules.agent.contracts import ToolSpec


def check(*, roles: list[str], spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """策略判定：先 Scope（硬拦），再判是否需审批（软分支）。

    args 保留入参位（后续版本按金额/密级做细粒度策略），当前不据此放行或拦截，
    避免出现「同一工具因参数不同而绕过 Scope」的口子。
    """
    _ = args
    if not has_scope(roles, spec.scope):
        return {
            "allowed": False,
            "approval_required": False,
            "scope": spec.scope,
            "reason": f"缺少 {spec.scope} 权限，无法调用工具 {spec.name}",
        }
    if spec.requires_approval:
        return {
            "allowed": True,
            "approval_required": True,
            "scope": spec.scope,
            "reason": f"工具 {spec.name} 属敏感操作，调用即进审批，账不动",
        }
    return {
        "allowed": True,
        "approval_required": False,
        "scope": spec.scope,
        "reason": "",
    }


def ensure_allowed(*, roles: list[str], spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """策略不通过直接抛 4006（端点/编排无需自己拼错误信封）。"""
    decision = check(roles=roles, spec=spec, args=args)
    if not decision["allowed"]:
        raise BusinessError(
            ErrorCode.TOOL_SCOPE_DENIED,
            f"{decision['reason']}（可联系管理员开通 {decision['scope']}）",
            403,
        )
    return decision
