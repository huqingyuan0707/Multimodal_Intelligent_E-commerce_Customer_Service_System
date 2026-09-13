"""对话端点（13 步问答侧，对齐 API 规范 §4.2/§5 + RAG 规范 §4）

链路：POST /chat → run_text_turn（检索→拼接→生成→校验→落库）→ ok()/2001；
POST /chat/stream → source/phase(retrieving/inspecting/generating/validating)
→ message 分片 → done（含引用/guard/faithfulness/trace_id/session_id/vision）。
图文轮 inspections 随请求透传（清洗+阈值重算在 service），低置信 done.need_human。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

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
    """对话请求体（端点私有 DTO；inspections 为上传步回执原样透传）。"""

    query: str
    thread_id: str | None = None
    security_level: str | None = None
    client_msg_id: str = ""
    image_ids: list[str] = []
    inspections: list[dict[str, Any]] = []


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
    if not payload.query.strip() and not payload.inspections:
        return fail(ErrorCode.PARAM_INVALID, "问题不能为空", 400)
    result = await chat_service.run_text_turn(
        db,
        user=user,
        query=payload.query,
        thread_id=payload.thread_id,
        client_msg_id=payload.client_msg_id,
        inspections=payload.inspections,
        image_ids=payload.image_ids,
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
            {
                "references": [],
                "guard": {"pass": False},
                "faithfulness": 0.0,
                "trace_id": "",
                "context": {"rounds": 0, "tokens": 0, "dropped": 0, "summarized": False},
            },
            f"{sid}:0",
        )
        return

    if not payload.query.strip() and not payload.inspections:
        return StreamingResponse(_empty(), media_type="text/event-stream")

    async def _gen() -> AsyncIterator[str]:
        yield _frame("source", {"name": "知识库"}, f"{sid}:0")
        yield _frame("phase", {"name": "retrieving"}, f"{sid}:1")
        seq = 2
        if payload.inspections:
            yield _frame("phase", {"name": "inspecting"}, f"{sid}:{seq}")
            seq += 1
        yield _frame("phase", {"name": "generating"}, f"{sid}:{seq}")
        seq += 1
        result = await chat_service.run_text_turn(
            db,
            user=user,
            query=payload.query,
            thread_id=payload.thread_id,
            client_msg_id=payload.client_msg_id,
            inspections=payload.inspections,
            image_ids=payload.image_ids,
        )
        yield _frame("phase", {"name": "validating"}, f"{sid}:{seq}")
        seq += 1
        chunks = chat_service.chunk_text(str(result["answer"]))
        for i, part in enumerate(chunks):
            yield _frame("message", {"content": part}, f"{sid}:{seq + i}")
        yield _frame(
            "done",
            {
                "references": result["references"],
                "guard": result["guard"],
                "faithfulness": result["faithfulness"],
                "trace_id": result["trace_id"],
                "session_id": result["session_id"],
                "vision": result.get("vision", []),
                "need_human": result.get("need_human", False),
                "context": result.get(
                    "context", {"rounds": 0, "tokens": 0, "dropped": 0, "summarized": False}
                ),
            },
            f"{sid}:{seq + len(chunks)}",
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")
