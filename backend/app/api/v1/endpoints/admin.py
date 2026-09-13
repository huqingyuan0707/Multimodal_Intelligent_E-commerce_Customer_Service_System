"""管理后台端点（租户/配额/审计框架，对齐 API 规范 §4.9 + 页面设计 §3.8）

链路：AdminView → 本模块 → admin_service → tenants/users/audit_logs。
端点只做「解析入参 + 调服务 + 组装信封」，事务提交收口在服务层（新文件零 db 直连门禁）。
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
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


class TenantCreateRequest(BaseModel):
    """新建租户入参（编码全局唯一，配额缺省走 Settings 默认）。"""

    code: str
    name: str
    plan: str = "trial"
    quota_tokens: int | None = None
    quota_concurrency: int | None = None


class QuotaRequest(BaseModel):
    """改配额入参（危险操作，前端双重 confirm）。"""

    quota_tokens: int
    quota_concurrency: int


class StatusRequest(BaseModel):
    """停服/恢复入参（active/suspended/disabled）。"""

    status: str


class RolesRequest(BaseModel):
    """改用户角色入参（逗号分隔，与种子口径一致）。"""

    roles: str


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """管理概览（租户数/用户数/停服数/审计数）。"""
    _ = user
    return ok(await admin_service.overview(db), "获取成功")


@router.get("/tenants")
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    keyword: str = Query(default="", max_length=64),
    plan: str = Query(default="", max_length=16),
    status: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """租户分页（keyword 匹配编码/名称）。"""
    _ = user
    return ok(
        await admin_service.list_tenants(
            db, keyword=keyword, plan=plan, status=status, page=page, size=size,
        ),
        "获取成功",
    )


@router.post("/tenants")
async def create_tenant(
    payload: TenantCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """新建租户（同步记 tenant.create 审计）。"""
    row = await admin_service.create_tenant(
        db, code=payload.code, name=payload.name, plan=payload.plan,
        quota_tokens=payload.quota_tokens,
        quota_concurrency=payload.quota_concurrency, actor=user.username,
    )
    return ok(admin_service.tenant_to_dict(row), "租户已创建")


@router.get("/tenants/{code}")
async def get_tenant(
    code: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """租户详情（含配额，供 QuotaForm 回显）。"""
    _ = user
    row = await admin_service.get_tenant_or_raise(db, code)
    return ok(admin_service.tenant_to_dict(row), "获取成功")


@router.put("/tenants/{code}/quota")
async def update_quota(
    code: str,
    payload: QuotaRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """改配额（同步记 tenant.quota 审计）。"""
    row = await admin_service.update_quota(
        db, code=code, quota_tokens=payload.quota_tokens,
        quota_concurrency=payload.quota_concurrency, actor=user.username,
    )
    return ok(admin_service.tenant_to_dict(row), "配额已更新")


@router.post("/tenants/{code}/status")
async def set_status(
    code: str,
    payload: StatusRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """停服/恢复（同步记 tenant.status 审计）。"""
    row = await admin_service.set_status(
        db, code=code, status=payload.status, actor=user.username,
    )
    return ok(admin_service.tenant_to_dict(row), "租户状态已更新")


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    keyword: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """用户分页（全局视角；tenant 为空=全部）。"""
    _ = user
    return ok(
        await admin_service.list_users(
            db, tenant=tenant, keyword=keyword, page=page, size=size,
        ),
        "获取成功",
    )


@router.put("/users/{user_id}/roles")
async def update_roles(
    user_id: str,
    payload: RolesRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """改用户角色（同步记 user.roles 审计）。"""
    row = await admin_service.update_user_roles(
        db, user_id=user_id, roles=payload.roles, actor=user.username,
    )
    return ok(admin_service.user_to_dict(row), "用户角色已更新")


@router.get("/audits")
async def list_audits(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    action: str = Query(default="", max_length=64),
    keyword: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """审计分页（只读倒序；keyword 匹配操作人/目标）。"""
    _ = user
    return ok(
        await admin_service.list_audits(
            db, tenant=tenant, action=action, keyword=keyword, page=page, size=size,
        ),
        "获取成功",
    )
