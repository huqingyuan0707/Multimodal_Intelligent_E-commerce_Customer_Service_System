"""经营大屏端点（数据源为大屏四指标 + 趋势 + 预警，对齐 API 规范 §4.7 大屏节）

链路：BizScreenView（30s 轮询）→ GET /screen/summary → 本模块（信封 + 1min 缓存）
      → screen_service.summary（PG/SQLite 聚合口径全在服务层）。
缓存：`screen:{tenant}:{range}`（数据模型 §4 大屏缓存行，TTL 1min）——大屏轮询 30s，
      不加缓存等于每 30s 全表聚合一次；Redis 不可用时 core.cache 自动降级进程内，不影响正确性。
权限：`screen:read`（粗粒度 shop 角色与 admin 亦放行，与前端的路由 roles 口径一致）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.exceptions import ErrorCode
from app.core.rbac import require_any_perm
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import screen_service

router = APIRouter(prefix="/screen", tags=["screen"])

SCREEN_RANGES = ("today", "week")
CACHE_TTL_SECONDS = 60


def _cache_key(user: CurrentUser, range_: str) -> str:
    """缓存键口径：数据模型 §4「大屏缓存」行 `screen:{tenant}:{range}`。

    admin 视角是全租户聚合，必须与单租户口径分键（否则 admin 的全量结果会被
    非 admin 命中，构成跨租户泄漏），故 admin 的分键位固定写 `all`。
    """
    scope = "all" if ("admin" in user.roles or "*" in user.roles) else user.tenant
    return f"screen:{scope}:{range_}"


@router.get("/summary")
async def summary(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_any_perm("screen:read", "shop", "admin")),
    range: str = Query(default="today", max_length=16),
) -> object:
    """大屏汇总：4 指标 + 近 7 日 GMV 趋势 + 预警下钻（admin 看全租户，否则本租户）。

    趋势恒为近 7 日（页面标题口径）；`range` 仅参与缓存分键，便于后续按周扩展示。
    """
    if range not in SCREEN_RANGES:
        return fail(ErrorCode.PARAM_INVALID, "range 仅支持 today/week", 400)
    key = _cache_key(user, range)
    cached = await cache.get_json(key)
    if isinstance(cached, dict):
        return ok(cached, "获取成功（缓存）")
    data = await screen_service.summary(db, user=user)
    await cache.set_json(key, data, CACHE_TTL_SECONDS)
    return ok(data, "获取成功")
