"""token 级流式单测（对齐测试方案 §2 + API 规范 §5）

覆盖：SSE 行解析纯函数；未启用直接不可用；无据拒答整段产出不断流；
正常轮增量外吐 + 全文落库 + done 同形；流中断后缀明示并照常 done。
运行（backend/ 目录）：pytest tests/test_chat_token_stream.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import Message
from app.db.session import get_engine, init_models
from app.services import chat_service, knowledge_service, llm_service

TENANT = "demo-tenant"
USER = "tester"


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（与 test_chat_stream 同口径，不走 lifespan/种子）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def demo_user() -> CurrentUser:
    """ContextVar 身份（assemble/finalize 经 access_context 取租户）。"""
    user = CurrentUser(username=USER, tenant=TENANT, roles=["cs"])
    set_current_user(user)
    return user


def _stub_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    """桩掉检索：固定返回 1 条退换货政策（断言引用落库用）。"""

    async def _refs(query: str, tenant: str, **kwargs: object) -> list[dict[str, object]]:
        _ = (query, tenant, kwargs)
        return [
            {
                "doc_id": "d1",
                "title": "退换货政策",
                "content": "支持 7 天无理由退货，质量问题 15 天退换。",
                "source": "退换货政策#3",
            }
        ]

    monkeypatch.setattr(knowledge_service, "retrieve", _refs)


def test_delta_from_sse_line() -> None:
    """SSE 行解析：正常增量 / [DONE] / 非 data 行 / 坏 JSON / 空 choices 全覆盖。"""
    assert (
        llm_service._delta_from_sse_line('data: {"choices": [{"delta": {"content": "你好"}}]}')
        == "你好"
    )
    assert llm_service._delta_from_sse_line("data: [DONE]") == ""
    assert llm_service._delta_from_sse_line(": keep-alive") == ""
    assert llm_service._delta_from_sse_line("data: not-json{") == ""
    assert llm_service._delta_from_sse_line('data: {"choices": []}') == ""
    assert llm_service._delta_from_sse_line('data: {"choices": [{"delta": {}}]}') == ""


async def test_acomplete_stream_disabled_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未启用不碰网络，直接不可用（调用方回退模板）。"""
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    with pytest.raises(llm_service.LlmUnavailableError):
        async for _ in llm_service.acomplete_stream([{"role": "user", "content": "hi"}]):
            pass


async def test_stream_reject_yields_once_and_persists(
    db: AsyncSession, demo_user: CurrentUser
) -> None:
    """无据拒答：整段一次 + 终态 rejected=True + 落 user/agent 两行。"""
    _ = demo_user
    items = [
        item
        async for item in chat_service.stream_text_turn(
            db, user=demo_user, query="今天天气怎么样", client_msg_id="s-rej"
        )
    ]
    assert len(items) == 2 and isinstance(items[0], str) and isinstance(items[1], dict)
    assert items[1]["rejected"] is True and items[1]["references"] == []
    rows = list(
        (
            await db.execute(
                select(Message).where(Message.session_id == str(items[1]["session_id"]))
            )
        ).scalars()
    )
    assert [r.role for r in rows] == ["user", "agent"]


async def test_stream_happy_path_deltas_then_result(
    db: AsyncSession, demo_user: CurrentUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正常轮：增量原样外吐 + 终态 answer 为拼接全文 + 引用落库 + done 同形。"""
    _stub_refs(monkeypatch)

    async def _tokens(messages: object, **kwargs: object) -> AsyncIterator[str]:
        _ = (messages, kwargs)
        yield "支持 7 天"
        yield "无理由退货 [1]。"

    monkeypatch.setattr(llm_service, "acomplete_stream", _tokens)
    items = [
        item
        async for item in chat_service.stream_text_turn(
            db, user=demo_user, query="退货政策是什么", client_msg_id="s-ok"
        )
    ]
    texts = [i for i in items if isinstance(i, str)]
    results = [i for i in items if isinstance(i, dict)]
    assert texts == ["支持 7 天", "无理由退货 [1]。"] and len(results) == 1
    final = results[0]
    assert final["answer"] == "支持 7 天无理由退货 [1]。"
    assert final["rejected"] is False and final["trace_id"] and final["session_id"]
    rows = list(
        (
            await db.execute(select(Message).where(Message.session_id == str(final["session_id"])))
        ).scalars()
    )
    assert [r.role for r in rows] == ["user", "agent"]
    assert rows[1].content == final["answer"]


async def test_stream_midway_break_marks_and_still_dones(
    db: AsyncSession, demo_user: CurrentUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """流中断（已有增量）：后缀明示 + 照常终态 done，不断流。"""
    _stub_refs(monkeypatch)

    async def _broken(messages: object, **kwargs: object) -> AsyncIterator[str]:
        _ = (messages, kwargs)
        yield "支持 7 天"
        raise llm_service.LlmUnavailableError("模型流不可达：ConnectError")

    monkeypatch.setattr(llm_service, "acomplete_stream", _broken)
    items = [
        item
        async for item in chat_service.stream_text_turn(
            db, user=demo_user, query="退货政策是什么", client_msg_id="s-brk"
        )
    ]
    results = [i for i in items if isinstance(i, dict)]
    assert len(results) == 1
    assert "生成中断" in str(results[0]["answer"])
    assert results[0]["rejected"] is False and results[0]["trace_id"]
