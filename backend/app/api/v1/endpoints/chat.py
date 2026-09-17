"""对话端点（13 步问答侧，对齐 API 规范 §4.2/§5 + RAG 规范 §4）

链路：POST /chat → run_text_turn（编排/检索→拼接→生成→校验→落库）→ ok()/2001；
POST /chat/stream → source/phase(retrieving/inspecting/generating) → message token 增量
→ phase(validating) → done（含引用/guard/faithfulness/trace_id/session_id/vision/
tool_calls/orchestration.notes）。
检索段走 Agent 编排（plan→executor→连接器，执行步骤 B 余项①接线），编排不可用回落
knowledge_service.retrieve 直调（开关 AGENT_CHAT_ORCHESTRATE 一键回退），两条路治理口径一致。
生成为模型 token 流（首字不等全文）；降级/重放为整段切片，帧形一致。
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

from app.config import settings
from app.core import cache
from app.core.exceptions import ErrorCode
from app.core.rbac import get_current_user
from app.core.responses import fail, ok
from app.core.user_context import CurrentUser
from app.db.session import get_db
from app.services import chat_service, handoff_service

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
    if not await cache.allow(
        f"rl:chat:{user.tenant}:{user.username}", settings.CHAT_RATE_LIMIT_PER_MIN, 60
    ):
        return fail(ErrorCode.CONVERSATION_LIMITED, "对话过于频繁，请 1 分钟后再试", 429)
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
) -> object:
    """流式问答：空问题仍 200 回单 done 帧（不断流）；事件 id 全帧可去重；超限 429 信封。"""
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
                "tool_calls": [],
                "orchestration": {"notes": []},
                "handoff": handoff_service.blank_handoff(),
            },
            f"{sid}:0",
        )
        return

    if not payload.query.strip() and not payload.inspections:
        return StreamingResponse(_empty(), media_type="text/event-stream")
    if not await cache.allow(
        f"rl:chat:{user.tenant}:{user.username}", settings.CHAT_RATE_LIMIT_PER_MIN, 60
    ):
        return fail(ErrorCode.CONVERSATION_LIMITED, "对话过于频繁，请 1 分钟后再试", 429)

    async def _gen() -> AsyncIterator[str]:
        yield _frame("source", {"name": "知识库"}, f"{sid}:0")
        yield _frame("phase", {"name": "retrieving"}, f"{sid}:1")
        seq = 2
        if payload.inspections:
            yield _frame("phase", {"name": "inspecting"}, f"{sid}:{seq}")
            seq += 1
        yield _frame("phase", {"name": "generating"}, f"{sid}:{seq}")
        seq += 1
        # token 增量直出：模型在线时首字不等全文；降级/重放为整段切片（帧形一致）。
        # 校验在全文到齐后（stream_text_turn 内），validating 帧随之后补。
        result: dict[str, object] = {}
        async for item in chat_service.stream_text_turn(
            db,
            user=user,
            query=payload.query,
            thread_id=payload.thread_id,
            client_msg_id=payload.client_msg_id,
            inspections=payload.inspections,
            image_ids=payload.image_ids,
        ):
            if isinstance(item, dict):
                result = item
                continue
            if item:
                yield _frame("message", {"content": item}, f"{sid}:{seq}")
                seq += 1
        yield _frame("phase", {"name": "validating"}, f"{sid}:{seq}")
        seq += 1
        yield _frame(
            "done",
            {
                "references": result.get("references", []),
                "guard": result.get("guard", {"pass": True}),
                "faithfulness": result.get("faithfulness", 0.0),
                "trace_id": result.get("trace_id", ""),
                "session_id": result.get("session_id", ""),
                # 赞踩反馈定位键（POST /mining/feedback 入参，前端气泡 thumbs 用）
                "message_id": result.get("message_id", ""),
                "vision": result.get("vision", []),
                "need_human": result.get("need_human", False),
                "context": result.get(
                    "context", {"rounds": 0, "tokens": 0, "dropped": 0, "summarized": False}
                ),
                "tool_calls": result.get("tool_calls", []),
                "orchestration": result.get("orchestration", {"notes": []}),
                # FR-5 第三级规则机器人：降级回复是否由确定性规则组装（未经过模型生成）
                "rulebot": result.get("rulebot", False),
                # 转人工规则表判定（C 步）：帧形不随分支变化（重放/降级同样带此字段）
                "handoff": result.get("handoff")
                or handoff_service.blank_handoff(session_id=str(result.get("session_id") or "")),
            },
            f"{sid}:{seq}",
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")
