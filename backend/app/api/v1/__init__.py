"""API v1 路由聚合（登录态统一挂载，对齐 API 规范 §3）

链路：router → endpoints.*（auth 公开，其余需 get_current_user）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    admin,
    admin_ops,
    admin_org,
    agent,
    agent_gateway,
    approvals,
    auth,
    chat,
    documents,
    finance,
    goods,
    governance,
    inventory,
    logistics,
    mining,
    multimodal,
    observability,
    orders,
    promos,
    purchase,
    reviews,
    risk,
    screen,
    sessions,
    studio,
    tasks,
    tickets,
    workbench,
)
from app.core.rbac import get_current_user

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chat.router, dependencies=[Depends(get_current_user)])
# 文本对话规范路径（任务 + FRDv2 口径）：/agent/chat 复用同一 router，/chat 保留兼容
api_router.include_router(chat.router, prefix="/agent", dependencies=[Depends(get_current_user)])
# Agent 内核（FR-3/FR-5）：/agent/tools 注册中心 + /agent/run 编排 + /agent/runtime/{id} 检查点
api_router.include_router(agent.router, dependencies=[Depends(get_current_user)])
# 外部 Agent 拉取出口（联动方案 §7）：入口权限在端点内 require_perm(agent:gateway) 把关
api_router.include_router(agent_gateway.router, dependencies=[Depends(get_current_user)])
api_router.include_router(sessions.router, dependencies=[Depends(get_current_user)])
api_router.include_router(studio.router, dependencies=[Depends(get_current_user)])
api_router.include_router(documents.router, dependencies=[Depends(get_current_user)])
api_router.include_router(mining.router, dependencies=[Depends(get_current_user)])
api_router.include_router(multimodal.router, dependencies=[Depends(get_current_user)])
api_router.include_router(observability.router, dependencies=[Depends(get_current_user)])
api_router.include_router(approvals.router, dependencies=[Depends(get_current_user)])
api_router.include_router(tasks.router, dependencies=[Depends(get_current_user)])
api_router.include_router(governance.router, dependencies=[Depends(get_current_user)])
# B 端业务路由：登录统一在挂载处强制，细粒度权限由各端点 require_any_perm 把关
api_router.include_router(goods.router, dependencies=[Depends(get_current_user)])
api_router.include_router(inventory.router, dependencies=[Depends(get_current_user)])
api_router.include_router(orders.router, dependencies=[Depends(get_current_user)])
api_router.include_router(orders.aftersales_router, dependencies=[Depends(get_current_user)])
api_router.include_router(promos.router, dependencies=[Depends(get_current_user)])
api_router.include_router(promos.members_router, dependencies=[Depends(get_current_user)])
api_router.include_router(reviews.router, dependencies=[Depends(get_current_user)])
api_router.include_router(tickets.router, dependencies=[Depends(get_current_user)])
api_router.include_router(workbench.router, dependencies=[Depends(get_current_user)])
api_router.include_router(logistics.router, dependencies=[Depends(get_current_user)])
api_router.include_router(admin.router, dependencies=[Depends(get_current_user)])
# 管理后台扩展面（密钥/SLO/消息模板/排班）：同前缀 /admin，同 admin 权限口径
api_router.include_router(admin_ops.router, dependencies=[Depends(get_current_user)])
api_router.include_router(admin_org.router, dependencies=[Depends(get_current_user)])
# 经营大屏（FRDv2 附录 D 大屏节）：全租户聚合视图，权限在端点内 screen:read/shop/admin
api_router.include_router(screen.router, dependencies=[Depends(get_current_user)])
# B 端二期（FR-10.3 采购 / FR-10.5 对账 / FR-12.1 风控）：细粒度权限由端点 require_any_perm 把关
api_router.include_router(purchase.router, dependencies=[Depends(get_current_user)])
api_router.include_router(finance.router, dependencies=[Depends(get_current_user)])
api_router.include_router(risk.router, dependencies=[Depends(get_current_user)])
