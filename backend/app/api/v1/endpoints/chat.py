"""对话端点（文本 SSE 主线，对齐 API 规范 §4.2/§5）

链路：POST /chat → run_text_turn 落库 → ok() / 2001 拒答；
POST /chat/stream → 先 source/phase → run_text_turn（幂等重放不调模型）
→ message 分片 → done（含引用/guard/faithfulness/trace_id/session_id）。
规范路径 /agent/chat（任务+FRDv2 口径），/chat 兼容别名（见 api/v1/__init__.py）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode
from app.core.rbac import get_current_user
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """对话请求体（端点私有 DTO）。"""

    query: str
    thread_id: str | None = None
    security_level: str | None = None
    client_msg_id: str = ""


def _frame(event: str, payload: dict[str, object], eid: str = "") -> str:
    """SSE 单帧：固定 id 行（事件幂等）+ event + 单行 data JSON。"""
    head = f"id: {eid}\n" if eid else ""
    return f"{head}event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> object:
    """非流式问答：落库后返回；无据 2001（前端按正常分支渲染拒答+转人工）。"""
    if not payload.query.strip():
        return fail(ErrorCode.PARAM_INVALID, "问题不能为空", 400)
    result = await chat_service.run_text_turn(
        db,
        user=user,
        query=payload.query,
        thread_id=payload.thread_id,
        client_msg_id=payload.client_msg_id,
    )
    if result.get("rejected"):
        return fail(ErrorCode.NO_EVIDENCE, str(result["answer"]), 200)
    return ok(result, "回答成功")


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    """流式问答：空问题仍 200 回单 done 帧（不断流）；事件 id 全帧可去重。"""
    sid = chat_service.stream_id_for(payload.client_msg_id or None)

    async def _empty() -> AsyncIterator[str]:
        yield _frame(
            "done",
            {"references": [], "guard": {"pass": False}, "faithfulness": 0.0, "trace_id": ""},
            f"{sid}:0",
        )
        return

    if not payload.query.strip():
        return StreamingResponse(_empty(), media_type="text/event-stream")

    async def _gen() -> AsyncIterator[str]:
        yield _frame("source", {"name": "知识库"}, f"{sid}:0")
        yield _frame("phase", {"name": "retrieving"}, f"{sid}:1")
        result = await chat_service.run_text_turn(
            db,
            user=user,
            query=payload.query,
            thread_id=payload.thread_id,
            client_msg_id=payload.client_msg_id,
        )
        chunks = chat_service.chunk_text(str(result["answer"]))
        for i, part in enumerate(chunks):
            yield _frame("message", {"content": part}, f"{sid}:{2 + i}")
        yield _frame(
            "done",
            {
                "references": result["references"],
                "guard": result["guard"],
                "faithfulness": result["faithfulness"],
                "trace_id": result["trace_id"],
                "session_id": result["session_id"],
            },
            f"{sid}:{2 + len(chunks)}",
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")
