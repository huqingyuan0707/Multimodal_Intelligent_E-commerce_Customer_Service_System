"""可观测汇总端点（数据看板数据源，对齐 API 规范 §4.6 + 页面设计 §3.7）

链路：DashboardView → GET /observability/summary → dashboard_service.summary。
端点只做「解析入参 + 调服务 + 组装信封」，聚合口径全在服务层。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode
from app.core.rbac import require_any_perm
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import dashboard_service

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/summary")
async def summary(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("ops", "admin")),
    range: str = Query(default="today", max_length=16),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> object:
    """看板汇总（指标卡 + 趋势 + 慢 Trace + 按租户归因分页；admin 看全租户，否则本租户）。"""
    if range not in ("today", "week"):
        return fail(ErrorCode.PARAM_INVALID, "range 仅支持 today/week", 400)
    return ok(
        await dashboard_service.summary(db, user=user, page=page, size=size, range_=range),
        "获取成功",
    )
