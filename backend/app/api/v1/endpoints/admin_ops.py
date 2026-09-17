"""管理后台扩展端点（密钥/SLO/消息模板/排班，对齐 API 规范 §4.9 + 页面设计 §3.8/§3.19）

链路：AdminView 密钥·SLO·消息·组织四窗格 → 本模块 → 各 admin 服务 → 业务表 + audit_logs。
拆分口径：`admin.py` 管租户/配额/用户/审计（存量四窗格），本模块管 §3.8/§3.19 的扩展面，
两者同前缀 `/admin`、同权限口径（`require_any_perm("admin")`），拆文件只为守住行数纪律。
端点只做「解析入参 + 调服务 + 组装信封」，事务提交收口在服务层。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_any_perm
from app.core.responses import ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import api_key_service, slo_service

router = APIRouter(prefix="/admin", tags=["admin-ops"])


class ApiKeyCreateRequest(BaseModel):
    """建密钥入参（明文仅在响应里回一次）。"""

    tenant: str
    name: str
    scopes: str = ""
    expires_at: str = ""


class ApiKeyStatusRequest(BaseModel):
    """密钥启停入参（active/disabled）。"""

    status: str


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    status: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """密钥分页（admin 全局视角；只回掩码，永不回明文与摘要）。"""
    _ = user
    return ok(
        await api_key_service.list_keys(db, tenant=tenant, status=status, page=page, size=size),
        "获取成功",
    )


@router.post("/api-keys")
async def create_api_key(
    payload: ApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """新建密钥：明文只在本响应出现一次，前端须提示「仅显示一次，请立即保存」。"""
    row, plain = await api_key_service.create_key(
        db,
        tenant=payload.tenant,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=api_key_service.parse_expires_at(payload.expires_at),
        actor=user.username,
    )
    return ok(
        {"item": api_key_service.key_to_dict(row), "plaintext": plain},
        "密钥已创建，明文仅显示一次",
    )


@router.post("/api-keys/{key_id}/rotate")
async def rotate_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """轮换密钥：旧口令立刻失效，新明文仅本响应可见。"""
    row, plain = await api_key_service.rotate_key(db, key_id=key_id, actor=user.username)
    return ok(
        {"item": api_key_service.key_to_dict(row), "plaintext": plain},
        "密钥已轮换，旧口令已失效",
    )


@router.post("/api-keys/{key_id}/status")
async def set_api_key_status(
    key_id: str,
    payload: ApiKeyStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """启用/禁用密钥（不删行，保留审计轨迹）。"""
    row = await api_key_service.set_status(
        db, key_id=key_id, status=payload.status, actor=user.username
    )
    return ok(api_key_service.key_to_dict(row), "密钥状态已更新")


class SloRuleRequest(BaseModel):
    """新建/覆盖 SLO 规则入参（tenant+metric 唯一，重复提交即改口径）。"""

    tenant: str
    metric: str
    operator: str = "gte"
    threshold: float
    window: str = "realtime"
    enabled: bool = True
    note: str = ""


class SloEnabledRequest(BaseModel):
    """规则启停入参。"""

    enabled: bool


@router.get("/slo/metrics")
async def slo_metrics(
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """指标目录 + 当前值（进程级口径，响应自带 scope 说明以便前端如实展示）。"""
    _ = user
    return ok(
        {
            "items": slo_service.metric_catalog(),
            "metric_scope": "process",
            "scope_note": "实时值取自本实例进程级聚合（含全部租户），非单租户口径",
        },
        "获取成功",
    )


@router.get("/slo/rules")
async def list_slo_rules(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """规则分页（含实时值对照与超标结论；无数据标 no_data 而非 0）。"""
    _ = user
    return ok(await slo_service.list_rules(db, tenant=tenant, page=page, size=size), "获取成功")


@router.post("/slo/rules")
async def upsert_slo_rule(
    payload: SloRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """新建或覆盖规则（同租户同指标只留一条）。"""
    row = await slo_service.upsert_rule(
        db,
        tenant=payload.tenant,
        metric=payload.metric,
        operator=payload.operator,
        threshold=payload.threshold,
        window=payload.window,
        enabled=payload.enabled,
        note=payload.note,
        actor=user.username,
    )
    return ok(
        slo_service.rule_to_dict(row, slo_service.current_values().get(row.metric)), "规则已保存"
    )


@router.post("/slo/rules/{rule_id}/enabled")
async def set_slo_enabled(
    rule_id: str,
    payload: SloEnabledRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """启用/停用规则（停用后不再参与超标判定）。"""
    row = await slo_service.set_enabled(
        db, rule_id=rule_id, enabled=payload.enabled, actor=user.username
    )
    return ok(
        slo_service.rule_to_dict(row, slo_service.current_values().get(row.metric)),
        "规则状态已更新",
    )


@router.delete("/slo/rules/{rule_id}")
async def delete_slo_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """删除规则（破坏性操作，前端必须二次确认）。"""
    await slo_service.delete_rule(db, rule_id=rule_id, actor=user.username)
    return ok({"id": rule_id}, "规则已删除")
