"""API v1 路由聚合（登录态统一挂载，对齐 API 规范 §3）

链路：router → endpoints.*（auth 公开，其余需 get_current_user）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import approvals, auth, chat, documents, governance, sessions, tasks
from app.core.rbac import get_current_user

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chat.router, dependencies=[Depends(get_current_user)])
api_router.include_router(sessions.router, dependencies=[Depends(get_current_user)])
api_router.include_router(documents.router, dependencies=[Depends(get_current_user)])
api_router.include_router(approvals.router, dependencies=[Depends(get_current_user)])
api_router.include_router(tasks.router, dependencies=[Depends(get_current_user)])
api_router.include_router(governance.router, dependencies=[Depends(get_current_user)])
