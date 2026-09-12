"""会话端点框架（对齐 API 规范 §4.3）

链路：GET/POST /sessions → service（current_user 口径）→ ok()。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.responses import ok

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def list_sessions() -> dict[str, object]:
    """会话列表占位。"""
    return ok([], "会话框架已就绪")


@router.post("")
async def create_session() -> dict[str, object]:
    """新建会话占位（前端本地先建 t-xxx 占位）。"""
    return ok({"id": ""}, "会话框架已就绪")


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict[str, object]:
    """会话详情占位，404 时前端回退 mock。"""
    return ok({"id": session_id, "messages": []}, "会话框架已就绪")


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict[str, object]:
    """删除会话占位（含记忆遗忘后续补）。"""
    return ok({"id": session_id}, "会话框架已就绪")
