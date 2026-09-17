"""管理后台「消息与组织」端点（对齐页面设计 §3.19 + FRD FR-12.2/FR-12.4）

链路：AdminView 消息窗格 / 组织窗格 → 本模块 → notify_service（模板/频控/到达率）、
      org_service（排班/绩效到人/离职冻结）→ 业务表 + audit_logs。
拆分口径：与 `admin_ops.py`（密钥/SLO）同样挂 `/admin` 同权限口径，按页面设计 §3.19
的「消息与组织」分组独立成文件，守住单文件行数纪律。
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
from app.services import notify_service, org_service

router = APIRouter(prefix="/admin", tags=["admin-org"])


class TemplateCreateRequest(BaseModel):
    """新建消息模板入参。"""

    tenant: str
    name: str
    channel: str = "sms"
    content: str = ""
    status: str = "draft"


class TemplateUpdateRequest(BaseModel):
    """改消息模板入参（全量覆盖，避免半更新语义歧义）。"""

    name: str
    channel: str
    content: str
    status: str


class TemplateStatusRequest(BaseModel):
    """模板启停入参。"""

    status: str


class NotifySendRequest(BaseModel):
    """按模板发送入参（网关未接入时照实回未送达）。"""

    tenant: str
    name: str
    user_ref: str


@router.get("/notify/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    channel: str = Query(default="", max_length=16),
    status: str = Query(default="", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """消息模板分页（含累计到达口径）。"""
    _ = user
    return ok(
        await notify_service.list_templates(
            db, tenant=tenant, channel=channel, status=status, page=page, size=size
        ),
        "获取成功",
    )


@router.post("/notify/templates")
async def create_template(
    payload: TemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """新建模板（租户内名称唯一）。"""
    row = await notify_service.create_template(
        db,
        tenant=payload.tenant,
        name=payload.name,
        channel=payload.channel,
        content=payload.content,
        status=payload.status,
        actor=user.username,
    )
    return ok(notify_service.template_to_dict(row), "模板已创建")


@router.put("/notify/templates/{template_id}")
async def update_template(
    template_id: str,
    payload: TemplateUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """改模板（名称撞同租户他表 1001）。"""
    row = await notify_service.update_template(
        db,
        template_id=template_id,
        name=payload.name,
        channel=payload.channel,
        content=payload.content,
        status=payload.status,
        actor=user.username,
    )
    return ok(notify_service.template_to_dict(row), "模板已更新")


@router.post("/notify/templates/{template_id}/status")
async def set_template_status(
    template_id: str,
    payload: TemplateStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """启停模板（正文为空的模板不允许启用）。"""
    row = await notify_service.set_template_status(
        db, template_id=template_id, status=payload.status, actor=user.username
    )
    return ok(notify_service.template_to_dict(row), "模板状态已更新")


@router.delete("/notify/templates/{template_id}")
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """删除模板（破坏性操作，前端必须二次确认）。"""
    await notify_service.delete_template(db, template_id=template_id, actor=user.username)
    return ok({"id": template_id}, "模板已删除")


@router.post("/notify/send")
async def send_notify(
    payload: NotifySendRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """按模板发一条（频控超限 1006；网关未接入则如实回未送达 + degraded）。"""
    return ok(
        await notify_service.send(
            db,
            tenant=payload.tenant,
            name=payload.name,
            user_ref=payload.user_ref,
            actor=user.username,
        ),
        "发送已受理",
    )


@router.get("/notify/reach")
async def notify_reach(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    """到达率报表（累计口径；无发送时 no_data 而非 0%）。"""
    _ = user
    return ok(await notify_service.reach_report(db, tenant=tenant), "获取成功")


# ==================== 组织：排班与绩效到人（FR-12.4） ====================


class ShiftCreateRequest(BaseModel):
    """登记排班入参（技能组取值与队列路由同源）。"""

    tenant: str
    username: str
    work_date: str
    start_time: str = "09:00"
    end_time: str = "18:00"
    skill: str = "general"
    note: str = ""


@router.get("/org/shifts")
async def list_shifts(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    username: str = Query(default="", max_length=64),
    work_date: str = Query(default="", max_length=10),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """排班分页（含技能组下拉数据，与 handoff_rules 同源）。"""
    _ = user
    return ok(
        await org_service.list_shifts(
            db, tenant=tenant, username=username, work_date=work_date, page=page, size=size
        ),
        "获取成功",
    )


@router.post("/org/shifts")
async def create_shift(
    payload: ShiftCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """登记一段班（坐席须已存在，技能组须为合法组名，结束须晚于开始）。"""
    row = await org_service.create_shift(
        db,
        tenant=payload.tenant,
        username=payload.username,
        work_date=payload.work_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        skill=payload.skill,
        note=payload.note,
        actor=user.username,
    )
    return ok(org_service.shift_to_dict(row), "排班已登记")


@router.delete("/org/shifts/{shift_id}")
async def delete_shift(
    shift_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
) -> dict[str, Any]:
    """删除排班（破坏性操作，前端必须二次确认）。"""
    await org_service.delete_shift(db, shift_id=shift_id, actor=user.username)
    return ok({"id": shift_id}, "排班已删除")


@router.get("/org/performance")
async def org_performance(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("admin")),
    tenant: str = Query(default="", max_length=64),
    username: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """绩效到人（坐席维度聚合，不含买家标识 —— 即「PII 脱敏」的落地口径）。"""
    _ = user
    return ok(
        await org_service.performance(db, tenant=tenant, username=username, page=page, size=size),
        "获取成功",
    )
