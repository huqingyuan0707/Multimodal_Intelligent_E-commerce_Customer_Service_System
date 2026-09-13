"""历史对话三层集成测试（Session→Message→Context，对齐 FR-1.4 + 数据模型 §2）

链路：ASGI 真调（临时库 + 种子 + 鉴权替换）→ 会话分页/翻页/重命名 →
多轮问答 → 历史进 LLM 断言 → 摘要刷新 → context 端点 → 删除级联。
运行（backend/ 目录）：pytest tests/test_sessions_history.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app
from app.services import context_service, llm_service

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])


async def _tester_override() -> CurrentUser:
    """鉴权替换：通配权限 + 写入 ContextVar（与 test_api_endpoints 同源）。"""
    set_current_user(TESTER)
    return TESTER


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 全量种子 + 鉴权替换的 ASGI 客户端。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'sess.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True
    app.dependency_overrides[get_current_user] = _tester_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert isinstance(data, dict)
    return data


async def _chat(client: httpx.AsyncClient, query: str, thread: str, key: str) -> dict[str, Any]:
    return await _ok(
        await client.post(
            "/api/v1/agent/chat",
            json={"query": query, "thread_id": thread, "client_msg_id": key},
        )
    )


def test_estimate_tokens_chinese_rate() -> None:
    """中文 1.5 字/token 统一口径（成本与预算同源）。"""
    assert context_service.estimate_tokens("") == 1
    assert context_service.estimate_tokens("退货政策是什么") == 5  # 7 字*2/3 上取整


def test_sanitize_masks_pii() -> None:
    """手机/身份证/邮箱脱敏 + 控制字符清理（纯函数）。"""
    out = context_service.sanitize_text("我手机13812345678，单\x00号查一下 a@b.com")
    assert "138****5678" in out and "\x00" not in out and "***@***" in out
    assert "13812345678" not in out


def test_build_history_block_drops_old_first() -> None:
    """超预算从旧往新丢轮（纯函数，不动摘要）。"""
    from app.db.models import Message

    rows = [
        Message(session_id="s", tenant="t", role="user" if i % 2 == 0 else "agent", content=f"消息{i}")
        for i in range(6)
    ]
    block, stats = context_service.build_history_block(rows, "", budget=12)
    assert stats["dropped"] >= 1 and "消息5" in block and "消息0" not in block
    assert context_service.build_history_block([], "") == ("", {"rounds": 0, "tokens": 0, "dropped": 0})


async def test_session_list_is_pagination_object(client: httpx.AsyncClient) -> None:
    """列表分页对象 + message_count（与知识库/B 端列表同口径）。"""
    first = await _ok(await client.post("/api/v1/sessions", json={"title": "退货咨询"}))
    await _chat(client, "退货政策是什么", first["id"], "k-list-1")
    page = await _ok(await client.get("/api/v1/sessions", params={"page": 1, "size": 20}))
    assert {"items", "total", "page", "size"} <= set(page)
    assert page["total"] >= 1 and page["items"][0]["message_count"] >= 2


async def test_detail_pagination_and_rename(client: httpx.AsyncClient) -> None:
    """详情倒序翻页 + has_more + 重命名（空标题 1001）。"""
    created = await _ok(await client.post("/api/v1/sessions", json={"title": "翻页"}))
    sid = str(created["id"])
    for i in range(3):
        await _chat(client, "退货政策是什么", sid, f"k-page-{i}")
    p1 = await _ok(await client.get(f"/api/v1/sessions/{sid}", params={"page": 1, "size": 2}))
    assert p1["total"] >= 6 and len(p1["messages"]) == 2 and p1["has_more"] is True
    p9 = await _ok(await client.get(f"/api/v1/sessions/{sid}", params={"page": 9, "size": 2}))
    assert p9["messages"] == [] and p9["has_more"] is False
    renamed = await _ok(await client.put(f"/api/v1/sessions/{sid}", json={"title": "改名成功"}))
    assert renamed["title"] == "改名成功"
    bad = await client.put(f"/api/v1/sessions/{sid}", json={"title": "  "})
    assert bad.json()["code"] == 1001


async def test_history_enters_llm_and_context_endpoint(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第二轮 LLM 入参含上轮（解指代），context 端点同源回放用量。"""
    seen: list[list[dict[str, str]]] = []

    async def _capture(messages: list[dict[str, str]]) -> llm_service.LlmReply:
        seen.append(messages)
        return llm_service.LlmReply(text="好的 [1]", model="stub", latency_ms=1, usage={})

    monkeypatch.setattr(llm_service, "complete", _capture)
    created = await _ok(await client.post("/api/v1/sessions", json={"title": "记忆"}))
    sid = str(created["id"])
    await _chat(client, "退货政策是什么", sid, "k-h-1")
    second = await _chat(client, "那换货呢", sid, "k-h-2")
    assert len(seen) == 2
    assert "【历史对话】" in seen[1][1]["content"] and "退货政策是什么" in seen[1][1]["content"]
    assert second["context"]["rounds"] >= 1 and second["context"]["tokens"] > 0
    ctx = await _ok(await client.get(f"/api/v1/sessions/{sid}/context"))
    assert ctx["rounds"] >= 1 and ctx["budget"] == settings.SESSION_TOKEN_BUDGET


async def test_summary_refresh_on_long_session(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """窗口满触发摘要（ROUNDS=1 时 3 轮必超限，summary 落库且 summarized=true）。"""
    monkeypatch.setattr(settings, "SESSION_HISTORY_ROUNDS", 1)
    created = await _ok(await client.post("/api/v1/sessions", json={"title": "长会话"}))
    sid = str(created["id"])
    last: dict[str, Any] = {}
    for i in range(3):
        last = await _chat(client, "退货政策是什么", sid, f"k-sum-{i}")
    assert last["context"]["summarized"] is True
    detail = await _ok(await client.get(f"/api/v1/sessions/{sid}"))
    assert detail["summary"] != ""


async def test_delete_session_forgets_all(client: httpx.AsyncClient) -> None:
    """删除级联遗忘（详情再查 404）。"""
    created = await _ok(await client.post("/api/v1/sessions", json={"title": "待删"}))
    sid = str(created["id"])
    await _chat(client, "退货政策是什么", sid, "k-del-1")
    deleted = await _ok(await client.delete(f"/api/v1/sessions/{sid}"))
    assert deleted["id"] == sid
    gone = await client.get(f"/api/v1/sessions/{sid}")
    assert gone.status_code == 404 and gone.json()["code"] == 1004
