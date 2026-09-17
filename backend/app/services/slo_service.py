"""SLO 规则服务（FR-8 SLO 告警，对齐页面设计 §3.8）

链路：/admin SLO 窗格 → 本模块 → slo_rules（阈值口径）+ observability.snapshot()（实时值）
      → 当场比对给出 current/breach；规则表**不落**「当前是否超标」的冗余状态（避免两处事实源）。

诚实性口径（如实暴露，不许把进程值读成租户值）：
- 实时值取自 core/observability 的**进程级内存聚合**（含本实例上的全部租户）。规则按租户存，
  只为权限与审计口径统一；值本身没有租户维度 —— 响应用 `metric_scope="process"` + scope_note 标注。
- 指标无数据时（如从未发生过转人工）current=None、no_data=true、breach=False，
  **不拿 0 冒充「0% 接起率」**（「没测过」与「0%」是两件事）。
- 聚合窗口现阶段只支持 realtime；today/week 要 JSONL 历史报表（E 步未完成），故不入白名单。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import observability
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import SloRule
from app.db.models_admin import SLO_OPERATORS, SLO_WINDOWS
from app.services.admin_service import dt_text, record_audit

# 指标目录（唯一出处：前端下拉与后端校验同源，禁止两边各写一份）。
# unit: ratio 比率 / seconds 秒 / count 次数；operator/threshold 是「建议默认值」不是强制值。
SLO_METRICS: dict[str, dict[str, Any]] = {
    "handoff_answer_rate": {
        "label": "30s 转人工接起率",
        "unit": "ratio",
        "operator": "gte",
        "threshold": 0.95,
    },
    "answer_p95_seconds": {
        "label": "转人工接起 P95",
        "unit": "seconds",
        "operator": "lte",
        "threshold": 30.0,
    },
    "llm_ok_rate": {
        "label": "模型调用成功率",
        "unit": "ratio",
        "operator": "gte",
        "threshold": 0.99,
    },
    "tool_ok_rate": {
        "label": "工具调用成功率",
        "unit": "ratio",
        "operator": "gte",
        "threshold": 0.98,
    },
    "reject_count": {
        "label": "拒答累计次数",
        "unit": "count",
        "operator": "lte",
        "threshold": 50.0,
    },
}


def _as_float(value: Any) -> float | None:
    """数值收敛：None / 非数值一律 None（宁可显示「无数据」，不显示编造值）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def current_values() -> dict[str, float | None]:
    """各指标实时值（进程级）。取不到的指标回落 None，由上层标 no_data。"""
    snap = observability.snapshot()
    handoff = snap.get("handoff") or {}
    counters = snap.get("counters") or {}
    return {
        "handoff_answer_rate": _as_float(handoff.get("answer_rate")),
        "answer_p95_seconds": _as_float(handoff.get("answer_p95_seconds")),
        "llm_ok_rate": _as_float(snap.get("llm_ok_rate")),
        "tool_ok_rate": _as_float(snap.get("tool_ok_rate")),
        # 计数类指标天然有值：0 次是真实观测（与「没测过」不同），故不置 None
        "reject_count": float(int(counters.get("chat.reject", 0))),
    }


def metric_catalog() -> list[dict[str, Any]]:
    """指标目录 + 当前实时值（前端「新建规则」下拉与值展示同源）。"""
    values = current_values()
    return [
        {
            "metric": metric,
            "label": meta["label"],
            "unit": meta["unit"],
            "operator": meta["operator"],
            "threshold": meta["threshold"],
            "current": values.get(metric),
        }
        for metric, meta in SLO_METRICS.items()
    ]


def _verdict(operator: str, threshold: float, current: float | None) -> dict[str, Any]:
    if current is None:
        return {"no_data": True, "breach": False}
    passed = current >= threshold if operator == "gte" else current <= threshold
    return {"no_data": False, "breach": not passed}


def rule_to_dict(row: SloRule, current: float | None) -> dict[str, Any]:
    """规则出参：口径字段 + 当场算出的实时值与结论（不在库里存结论）。"""
    meta = SLO_METRICS.get(row.metric, {})
    verdict = _verdict(row.operator, float(row.threshold), current)
    return {
        "id": row.id,
        "tenant": row.tenant,
        "metric": row.metric,
        "metric_label": meta.get("label", row.metric),
        "unit": meta.get("unit", "count"),
        "operator": row.operator,
        "threshold": float(row.threshold),
        "window": row.window,
        "enabled": bool(row.enabled),
        "note": row.note,
        "current": current,
        "no_data": verdict["no_data"],
        # 只有启用中的规则才谈「超标」：停用规则不参与判定，避免误读成在告警
        "breach": bool(row.enabled) and verdict["breach"],
        "created_at": dt_text(row.created_at),
        "updated_at": dt_text(row.updated_at),
    }


async def list_rules(
    db: AsyncSession,
    *,
    tenant: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """规则分页（含实时值对照）。metric_scope/scope_note 如实标注值的来源层级。"""
    stmt = select(SloRule)
    if tenant.strip():
        stmt = stmt.where(SloRule.tenant == tenant.strip())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(SloRule.created_at.desc()).offset((page - 1) * size).limit(size)
            )
        ).scalars()
    )
    values = current_values()
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [rule_to_dict(row, values.get(row.metric)) for row in rows],
        "metric_scope": "process",
        "scope_note": "实时值取自本实例进程级聚合（含全部租户），非单租户口径",
        "windows": list(SLO_WINDOWS),
    }


async def get_rule_or_raise(db: AsyncSession, rule_id: str) -> SloRule:
    row = (await db.execute(select(SloRule).where(SloRule.id == rule_id))).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "SLO 规则不存在", 404)
    return row


async def upsert_rule(
    db: AsyncSession,
    *,
    tenant: str,
    metric: str,
    operator: str,
    threshold: float,
    window: str = "realtime",
    enabled: bool = True,
    note: str = "",
    actor: str = "",
) -> SloRule:
    """新建或覆盖规则（按 tenant+metric 唯一，重复提交即改阈值，无需先删）。"""
    cleaned_tenant = (tenant or "").strip()
    if not cleaned_tenant:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择规则所属租户")
    if metric not in SLO_METRICS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"指标非法：{metric}")
    if operator not in SLO_OPERATORS:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, "比较方向只能是 gte（目标下限）或 lte（目标上限）"
        )
    if window not in SLO_WINDOWS:
        raise BusinessError(ErrorCode.PARAM_INVALID, f"聚合窗口当前仅支持 {'/'.join(SLO_WINDOWS)}")
    if threshold < 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "阈值不能为负数")

    row = (
        await db.execute(
            select(SloRule).where(SloRule.tenant == cleaned_tenant, SloRule.metric == metric)
        )
    ).scalar_one_or_none()
    created = row is None
    if row is None:
        row = SloRule(tenant=cleaned_tenant, metric=metric)
        db.add(row)
        # 列默认值要等 flush 才落地，此刻读会拿到 None（float(None) 直接炸）：新建不留 before 快照
        before: dict[str, Any] = {}
    else:
        before = {
            "operator": row.operator,
            "threshold": float(row.threshold),
            "enabled": bool(row.enabled),
        }
    row.operator = operator
    row.threshold = float(threshold)
    row.window = window
    row.enabled = bool(enabled)
    row.note = (note or "")[:200]
    await db.flush()
    await record_audit(
        db,
        tenant=cleaned_tenant,
        actor=actor,
        action="slo.upsert",
        target=metric,
        detail={
            "created": created,
            "from": before,
            "to": {"operator": operator, "threshold": float(threshold), "enabled": bool(enabled)},
        },
    )
    await db.commit()
    return row


async def set_enabled(db: AsyncSession, *, rule_id: str, enabled: bool, actor: str = "") -> SloRule:
    """启用/停用规则（停用后不再参与超标判定）。"""
    row = await get_rule_or_raise(db, rule_id)
    old = bool(row.enabled)
    row.enabled = bool(enabled)
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="slo.enable",
        target=row.metric,
        detail={"from": old, "to": bool(enabled)},
    )
    await db.commit()
    return row


async def delete_rule(db: AsyncSession, *, rule_id: str, actor: str = "") -> None:
    """删除规则（破坏性操作，前端须二次确认；审计留档删前的口径）。"""
    row = await get_rule_or_raise(db, rule_id)
    detail = {
        "metric": row.metric,
        "operator": row.operator,
        "threshold": float(row.threshold),
    }
    tenant = row.tenant
    await db.delete(row)
    await db.flush()
    await record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="slo.delete",
        target=row.metric,
        detail=detail,
    )
    await db.commit()
