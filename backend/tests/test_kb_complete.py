"""知识库 P1 补齐单测（BM25/精排/缓存/检索测试/版本回滚/生命周期/引用统计，对齐 FR-4/FR-13）

链路：纯函数直测（bm25/rerank/标题命中）+ 临时库服务级直测（检索门禁/缓存/版本/流转/统计）。
运行（backend/ 目录）：pytest tests/test_kb_complete.py
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.cache import get_json
from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.models import KbDoc, Message
from app.db.session import get_engine, init_models
from app.services import document_service, knowledge_service, rerank_service

TENANT = "kb-complete-tenant"


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（引擎单例夹具后还原；与旧测试文件同构，不跨文件复用）。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'kb.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


async def _mkdoc(
    db: AsyncSession,
    title: str,
    content: str,
    raw: bytes,
    topic: str = "",
    status: str = "published",
) -> KbDoc:
    row, _ = await document_service.get_or_create_doc(
        db, tenant=TENANT, title=title, content=content, raw=raw, topic=topic, status=status
    )
    return row


def test_bm25_prefers_relevant() -> None:
    """BM25：相关块得分高于无关块；空 query 全 0（纯函数）。"""
    chunks = {
        "a": Counter(knowledge_service._terms("七天无理由退货政策全文")),
        "b": Counter(knowledge_service._terms("今日天气晴朗适合出行")),
    }
    freq: dict[str, int] = {}
    for tf in chunks.values():
        for term in tf:
            freq[term] = freq.get(term, 0) + 1
    scores = knowledge_service.bm25_scores(["七天", "天无", "退货"], chunks, freq, 8.0, 2)
    assert scores["a"] > scores["b"] >= 0.0
    empty = knowledge_service.bm25_scores([], chunks, freq, 8.0, 2)
    assert empty == {"a": 0.0, "b": 0.0}


def test_rerank_keeps_fused_order_breaks_ties() -> None:
    """精排：RRF 主序不被推翻；RRF 打平时 BM25 高者居前。"""
    assert rerank_service.rerank({"a": 0.03, "b": 0.02}, {"a": 0.1, "b": 0.9})[0] == "a"
    tied = rerank_service.rerank(
        {"a": 0.02, "b": 0.02}, {"a": 0.1, "b": 0.1}, bm25={"a": 1.0, "b": 5.0}
    )
    assert tied[0] == "b"
    assert rerank_service._title_hit("退货政策", "退货政策说明") is True
    assert rerank_service._title_hit("退货政策", "今日天气") is False


async def test_retrieve_only_published(db: AsyncSession) -> None:
    """检索只收 published：草稿同文不可见，发布后可见。"""
    await _mkdoc(db, "草稿退货说明", "七天无理由退货政策草稿全文", b"draft-1", status="draft")
    assert await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"]) == []
    row, _ = await document_service.get_or_create_doc(
        db, tenant=TENANT, title="线上退货说明", content="七天无理由退货政策线上全文", raw=b"pub-1"
    )
    assert row.status == "published"
    refs = await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"])
    assert refs and refs[0]["doc_id"] == row.id
    assert "bm25" in refs[0] and "rrf" in refs[0]


async def test_retrieve_cache_hit_and_bypass(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """热点缓存：命中写缓存键；TTL=0 则旁路；写操作 bump 后旧键失效。"""
    await _mkdoc(db, "缓存退货说明", "七天无理由退货政策缓存全文", b"cache-1")
    levels = knowledge_service.visible_levels(["ops"])
    key = knowledge_service._cache_key(TENANT, levels, "all", settings.TOP_K, "七天无理由退货")
    monkeypatch.setattr(settings, "RAG_CACHE_TTL", 60)
    first = await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"])
    assert first and await get_json(key) is not None
    knowledge_service.bump_corpus(TENANT)
    # bump 只让新键失效（旧键按 TTL 自然过期，此处断言新键未命中即重算）
    new_key = knowledge_service._cache_key(TENANT, levels, "all", settings.TOP_K, "七天无理由退货")
    assert new_key != key and await get_json(new_key) is None
    second = await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"])
    assert second and await get_json(new_key) is not None
    # TTL=0 旁路：不读不写——再 bump 出更新的键，检索后它仍是空的
    monkeypatch.setattr(settings, "RAG_CACHE_TTL", 0)
    knowledge_service.bump_corpus(TENANT)
    newest_key = knowledge_service._cache_key(
        TENANT, levels, "all", settings.TOP_K, "七天无理由退货"
    )
    await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"])
    assert await get_json(newest_key) is None


async def test_retrieve_debug_shape(db: AsyncSession) -> None:
    """检索测试口径：引用含各路分数 + 过滤原因（运营预览用）。"""
    await _mkdoc(db, "调试退货说明", "七天无理由退货政策调试全文", b"debug-1")
    data = await knowledge_service.retrieve_debug("七天无理由退货", TENANT, db, roles=["ops"])
    assert data["channel"] == "all" and "public" in data["levels"]
    assert set(data["filtered"]) == {"total_docs", "expired", "channel_cut", "below_threshold"}
    assert data["refs"] and "bm25" in data["refs"][0]
    empty = await knowledge_service.retrieve_debug("量子纠缠退火算法原理", TENANT, db)
    assert empty["refs"] == [] and empty["filtered"]["below_threshold"] is True


async def test_versions_and_rollback(db: AsyncSession) -> None:
    """版本历史只追加；回滚=旧内容新版本（不覆盖旧版）。"""
    row = await _mkdoc(db, "版本文档", "第一版内容", b"ver-1")
    await document_service.update_doc(
        db,
        tenant=TENANT,
        doc_id=row.id,
        title="版本文档",
        content="第二版内容",
        security_level="internal",
        channels=["all"],
        actor="ops",
    )
    versions = await document_service.list_versions(db, tenant=TENANT, doc_id=row.id)
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["action"] == "update" and versions[0]["actor"] == "ops"
    rolled = await document_service.rollback_doc(
        db, tenant=TENANT, doc_id=row.id, version=1, actor="ops"
    )
    assert rolled.version == 3 and rolled.content == "第一版内容"
    versions = await document_service.list_versions(db, tenant=TENANT, doc_id=row.id)
    assert [v["version"] for v in versions] == [3, 2, 1]
    try:
        await document_service.rollback_doc(db, tenant=TENANT, doc_id=row.id, version=99)
        raise AssertionError("不存在的版本应 404")
    except BusinessError as exc:
        assert exc.code == ErrorCode.NOT_FOUND


async def test_lifecycle_dual_review(db: AsyncSession) -> None:
    """生命周期：draft→review→published（换人复核）→archived→draft；非法流转 1001。"""
    row = await _mkdoc(db, "审核文档", "待审核内容", b"life-1", status="draft")
    assert await knowledge_service.retrieve("待审核内容", TENANT, db=db, roles=["ops"]) == []
    row = await document_service.transition_doc(
        db, tenant=TENANT, doc_id=row.id, action="submit", actor="alice"
    )
    assert row.status == "review" and row.submitted_by == "alice"
    try:
        await document_service.transition_doc(
            db, tenant=TENANT, doc_id=row.id, action="publish", actor="alice"
        )
        raise AssertionError("自己审自己应 1001")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    row = await document_service.transition_doc(
        db, tenant=TENANT, doc_id=row.id, action="publish", actor="bob"
    )
    assert row.status == "published" and row.published_by == "bob"
    assert await knowledge_service.retrieve("待审核内容", TENANT, db=db, roles=["ops"]) != []
    row = await document_service.transition_doc(
        db, tenant=TENANT, doc_id=row.id, action="archive", actor="bob"
    )
    assert row.status == "archived"
    assert await knowledge_service.retrieve("待审核内容", TENANT, db=db, roles=["ops"]) == []
    row = await document_service.transition_doc(
        db, tenant=TENANT, doc_id=row.id, action="reopen", actor="bob"
    )
    assert row.status == "draft" and row.submitted_by == ""
    try:
        await document_service.transition_doc(
            db, tenant=TENANT, doc_id=row.id, action="publish", actor="bob"
        )
        raise AssertionError("草稿直接发布应 1001")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID


async def test_doc_stats_cited_and_idle(db: AsyncSession) -> None:
    """引用统计：messages.citations 聚合命中；0 引用超 30 天进复核清单。"""
    hot = await _mkdoc(db, "热门文档", "七天无理由退货热门全文", b"hot-1", topic="退换售后")
    await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"])
    refs = await knowledge_service.retrieve("七天无理由退货", TENANT, db=db, roles=["ops"])
    assert refs
    db.add(
        Message(
            session_id="s1",
            tenant=TENANT,
            role="agent",
            content="答复",
            citations=json.dumps(
                [{"doc_id": hot.id, "source": f"{hot.id}#0", "score": 0.9}],
                ensure_ascii=False,
            ),
        )
    )
    await db.commit()
    cold = await _mkdoc(db, "冷门文档", "无人问津的陈旧政策全文", b"cold-1", topic="退换售后")
    old = datetime.now() - timedelta(days=45)
    await db.execute(update(KbDoc).where(KbDoc.id == cold.id).values(created_at=old))
    await db.commit()
    stats = await document_service.doc_stats(db, tenant=TENANT)
    assert stats["total"] >= 2 and stats["by_status"].get("published", 0) >= 2
    topics = {t["topic"]: t for t in stats["topics"]}
    assert topics["退换售后"]["cited"] >= 1
    idle_ids = [r["doc_id"] for r in stats["idle_review"]]
    assert cold.id in idle_ids and hot.id not in idle_ids
