"""对话端点（真实 RAG 问答 + SSE，对齐 API 规范 §4.2/§5）

链路：POST /chat → chat_service.answer → ok() / 2001 拒答；
POST /chat/stream → phase/message/done 真实帧（Nginx 需 proxy_buffering off）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.exceptions import ErrorCode
from app.core.responses import fail, ok
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """对话请求体（端点私有 DTO）。"""

    query: str
    thread_id: str | None = None
    security_level: str | None = None


@router.post("")
async def chat(payload: ChatRequest) -> object:
    """非流式问答：有据 ok()，无据 2001（前端按正常分支渲染拒答+转人工）。"""
    if not payload.query.strip():
        return fail(ErrorCode.PARAM_INVALID, "问题不能为空", 400)
    try:
        result = await chat_service.answer(payload.query)
    except chat_service.NoEvidence as exc:
        return fail(ErrorCode.NO_EVIDENCE, str(exc), 200)
    return ok(result, "回答成功")


def _frame(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _real_events(query: str) -> AsyncIterator[str]:
    """真实帧：phase 检索中 → message 分片 → done（含引用/guard/faithfulness/trace）。"""
    yield _frame("phase", {"name": "retrieving"})
    try:
        result = await chat_service.answer(query)
    except chat_service.NoEvidence as exc:
        yield _frame("message", {"content": str(exc)})
        yield _frame(
            "done",
            {"references": [], "guard": {"pass": True}, "faithfulness": 0.0, "trace_id": ""},
        )
        return
    answer = str(result["answer"])
    half = max(1, len(answer) // 2)
    yield _frame("message", {"content": answer[:half]})
    yield _frame("message", {"content": answer[half:]})
    yield _frame(
        "done",
        {
            "references": result["references"],
            "guard": result["guard"],
            "faithfulness": result["faithfulness"],
            "trace_id": result["trace_id"],
        },
    )


@router.post("/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """流式问答（空问题直接 400，非流）。"""
    if not payload.query.strip():
        async def _empty() -> AsyncIterator[str]:
            yield _frame("done", {"references": [], "guard": {"pass": False}, "faithfulness": 0.0, "trace_id": ""})
            return

        return StreamingResponse(_empty(), media_type="text/event-stream")
    return StreamingResponse(_real_events(payload.query), media_type="text/event-stream")
