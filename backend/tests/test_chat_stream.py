"""文本轮次落库与流式幂等单测（对齐测试方案 §2 + API 规范 §4.2/§5）

覆盖：ensure_session 新建/复用/他人 thread 隔离；同 client_msg_id 双调只落一行；
重放不再调模型；stream_id 确定性；message 分片；/agent/chat/stream 四事件+id 行+
done.session_id 落库可查。
运行（backend/ 目录）：pytest tests/test_chat_stream.py
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.models import Message
from app.db.seed import ensure_kb_seed
from app.db.session import get_engine, init_models
from app.main import app
from app.services import chat_service, llm_service, session_service

TENANT = "demo-tenant"
USER = "tester"
HIT_QUERY = "退货政策是什么"
MISS_QUERY = "今天天气怎么样"
# 种子目录（模块级常量：async 测试内禁阻塞 pathlib 操作，见 ASYNC240）
KB_SEED_ABS = str(Path(__file__).resolve().parents[2] / "docs" / "knowledge-base")


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（服务层直测，不走 lifespan/种子）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def demo_user() -> CurrentUser:
    """ContextVar 身份（answer() 经 access_context 取租户，不断链）。"""
    user = CurrentUser(username=USER, tenant=TENANT, roles=["cs"])
    set_current_user(user)
    return user


def _canned_answer(monkeypatch: pytest.MonkeyPatch, calls: list[str]):
    """桩掉 answer()：固定带 [1] 引用的答复并计数调用次数（断言重放不再调模型）。"""
    real_retrieve = chat_service.knowledge_service.retrieve

    async def _counted(query: str, *args: object, **kwargs: object) -> dict[str, object]:
        calls.append(query)
        refs = await real_retrieve(query, TENANT)
        text = "支持 7 天无理由退货 [1]，质量问题 15 天退换 [1]。"
        return {
            "answer": text,
            "references": refs,
            "guard": {"pass": True, "degraded": False},
            "faithfulness": chat_service.faithfulness(text, len(refs)),
            "model": "stub",
            "degraded": False,
            "trace_id": "testtrace001",
        }

    monkeypatch.setattr(chat_service, "answer", _counted)


async def test_ensure_session_create_reuse_foreign(
    db: AsyncSession, demo_user: CurrentUser
) -> None:
    """新建落标题 → 本人 thread 复用 → 他人 thread 隔离新建。"""
    s1, created = await session_service.ensure_session(
        db, tenant=TENANT, username=USER, thread_id=None, title_hint="退货政策是什么请问"
    )
    assert created and len(s1.title) <= 20 and "退货" in s1.title
    s2, created2 = await session_service.ensure_session(
        db, tenant=TENANT, username=USER, thread_id=s1.id, title_hint="xxx"
    )
    assert not created2 and s2.id == s1.id
    s3, created3 = await session_service.ensure_session(
        db, tenant="other", username="mallory", thread_id=s1.id, title_hint="hi"
    )
    assert created3 and s3.id != s1.id


async def test_run_text_turn_persists_two_rows(
    db: AsyncSession, demo_user: CurrentUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """整轮落 user+agent 两行，引用/guard/trace 随行，done 可直接透传。"""
    calls: list[str] = []
    _canned_answer(monkeypatch, calls)
    result = await chat_service.run_text_turn(
        db, user=demo_user, query=HIT_QUERY, client_msg_id="k-1"
    )
    assert result["session_id"] and result["replayed"] is False
    assert result["references"] and result["trace_id"] == "testtrace001"
    rows = list(
        (
            await db.execute(select(Message).where(Message.session_id == str(result["session_id"])))
        ).scalars()
    )
    assert [r.role for r in rows] == ["user", "agent"]
    assert rows[1].client_msg_id == "k-1"
    assert json.loads(rows[1].citations)[0]["title"] == "退换货政策"


async def test_run_text_turn_idempotent_replay_skips_llm(
    db: AsyncSession, demo_user: CurrentUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同键双调：模型只调一次，第二轮 replay 复用内容与 trace_id。"""
    calls: list[str] = []
    _canned_answer(monkeypatch, calls)
    first = await chat_service.run_text_turn(
        db, user=demo_user, query=HIT_QUERY, client_msg_id="k-2"
    )
    second = await chat_service.run_text_turn(
        db,
        user=demo_user,
        query=HIT_QUERY,
        thread_id=str(first["session_id"]),
        client_msg_id="k-2",
    )
    assert calls == [HIT_QUERY]
    assert second["replayed"] is True
    assert second["answer"] == first["answer"] and second["trace_id"] == first["trace_id"]
    total = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.session_id == str(first["session_id"]))
        )
    ).scalar_one()
    assert total == 2


async def test_run_text_turn_reject_persists(db: AsyncSession, demo_user: CurrentUser) -> None:
    """无据拒答同样落库（rejected=True），刷新历史可见拒答话术。"""
    result = await chat_service.run_text_turn(
        db, user=demo_user, query=MISS_QUERY, client_msg_id="k-3"
    )
    assert result["rejected"] is True and result["references"] == []
    total = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.session_id == str(result["session_id"]))
        )
    ).scalar_one()
    assert total == 2


def test_stream_id_deterministic() -> None:
    """同键同 id（重放帧 id 一致，前端天然去重）；无键随机。"""
    assert chat_service.stream_id_for("k-1") == chat_service.stream_id_for("k-1")
    assert chat_service.stream_id_for("k-1") != chat_service.stream_id_for("k-2")
    assert chat_service.stream_id_for(None) != chat_service.stream_id_for(None)


def test_chunk_text_respects_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """分片长度走 Settings.SSE_CHUNK_CHARS，短文本单片。"""
    monkeypatch.setattr(settings, "SSE_CHUNK_CHARS", 5)
    assert chat_service.chunk_text("abcdefg") == ["abcde", "fg"]
    assert chat_service.chunk_text("hi") == ["hi"]


async def test_agent_stream_endpoint_events_and_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端点级：/agent/chat/stream 四事件有序 + id 行 + done.session_id，落库可查且重发不翻倍。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'e.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    # 端到端走 DB 双路链：先灌 29 篇种子（SEED_TENANT 默认 demo-tenant 与 TENANT 一致）
    monkeypatch.setattr(settings, "KB_SEED_DIR", KB_SEED_ABS)
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as seed_db:
        assert await ensure_kb_seed(seed_db) is True

    async def _tester() -> CurrentUser:
        user = CurrentUser(username=USER, tenant=TENANT, roles=["cs"])
        set_current_user(user)
        return user

    async def _stub_complete(messages: object, **kwargs: object) -> llm_service.LlmReply:
        return llm_service.LlmReply(text="支持 7 天无理由退货 [1]。", model="stub", latency_ms=1)

    async def _stub_stream(messages: object, **kwargs: object) -> AsyncIterator[str]:
        # 端点已走 token 流：桩住增量口，整段一次外吐（帧形不断言粒度，只断言有序与幂等）
        yield "支持 7 天无理由退货 [1]。"

    monkeypatch.setattr(llm_service, "complete", _stub_complete)
    monkeypatch.setattr(llm_service, "acomplete_stream", _stub_stream)
    app.dependency_overrides[get_current_user] = _tester
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            body = {"query": HIT_QUERY, "client_msg_id": "e2e-1"}
            r = await client.post("/api/v1/agent/chat/stream", json=body)
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = [
                line.split("event: ", 1)[1]
                for line in r.text.splitlines()
                if line.startswith("event: ")
            ]
            assert events[0] == "source" and events[1] == "phase"
            assert "message" in events and events[-1] == "done"
            ids = [
                line.split("id: ", 1)[1] for line in r.text.splitlines() if line.startswith("id: ")
            ]
            assert len(ids) == len(events) and len(set(ids)) == len(ids)
            done_raw = r.text.split("event: done")[1].split("data: ", 1)[1].split("\n")[0]
            done = json.loads(done_raw)
            assert done["references"] and done["trace_id"] and done["session_id"]

            detail = (await client.get(f"/api/v1/sessions/{done['session_id']}")).json()["data"]
            # 详情消息倒序（page=1 最新页），反转即正序 [user, agent]
            assert [m["role"] for m in reversed(detail["messages"])] == ["user", "agent"]
            assert "#" in detail["messages"][0]["citations"][0]["source"]

            r2 = await client.post("/api/v1/agent/chat/stream", json=body)
            assert r2.status_code == 200
            detail2 = (await client.get(f"/api/v1/sessions/{done['session_id']}")).json()["data"]
            assert len(detail2["messages"]) == 2
    finally:
        app.dependency_overrides.clear()
