"""RAG 全链路单测（上传→切分→双路召回→治理→拒答→作答，对齐 RAG 规范 §2/§3）

覆盖：主题切分（标题起块/超长硬切）；租户隔离；密级可见集；
生效期过期不可见；同 doc 多样性裁剪；阈值拒答；answer 有据含引用 + faithfulness；
reindex 重建分块并落 task。
运行（backend/ 目录）：pytest tests/test_rag_chain.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import ensure_kb_seed
from app.db.session import get_engine, init_models
from app.services import chat_service, document_service, knowledge_service

TENANT = "rag-chain-tenant"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（引擎单例夹具后还原）。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def seeded_db(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncSession]:
    """29 篇种子 + 治理探针文档（过期/机密/跨租户）。"""
    monkeypatch.setattr(settings, "KB_SEED_DIR", str(ROOT / "docs" / "knowledge-base"))
    monkeypatch.setattr(settings, "SEED_TENANT", TENANT)
    assert await ensure_kb_seed(db) is True
    expired, _ = await document_service.get_or_create_doc(
        db, tenant=TENANT, title="过期政策", content="已下线的旧退货政策全文", raw=b"expired-1"
    )
    await document_service.update_doc(
        db,
        tenant=TENANT,
        doc_id=expired.id,
        title="过期政策",
        content="已下线的旧退货政策全文",
        security_level="public",
        channels=["all"],
        valid_from="",
        valid_to="2020-01-01",
    )
    secret, _ = await document_service.get_or_create_doc(
        db, tenant=TENANT, title="机密定价", content="内部成本价目表", raw=b"secret-1"
    )
    await document_service.update_doc(
        db,
        tenant=TENANT,
        doc_id=secret.id,
        title="机密定价",
        content="内部成本价目表",
        security_level="confidential",
        channels=["all"],
    )
    await document_service.get_or_create_doc(
        db, tenant="other-tenant", title="他租户退货", content="他租户退货政策", raw=b"other-1"
    )
    yield db


def test_split_chunks_by_heading() -> None:
    """标题起块 + 超长硬切（纯函数，不碰 DB）。"""
    parts = document_service.split_chunks("# 总则\n## 退货\n政策A\n## 换货\n政策B\n")
    assert len(parts) == 2 and parts[0].startswith("# 总则\n## 退货")
    long_text = "# 长文\n" + "字\n" * 2000
    capped = document_service.split_chunks(long_text)
    assert len(capped) > 1 and all(len(part) <= settings.KB_CHUNK_CHARS for part in capped)


def test_visible_levels() -> None:
    """密级可见集：空角色只见公开；在岗见内部；kb 见机密。"""
    assert knowledge_service.visible_levels([]) == {"public"}
    assert knowledge_service.visible_levels(["cs"]) == {"public", "internal"}
    assert knowledge_service.visible_levels(["kb"]) == {"public", "internal", "confidential"}


async def test_retrieve_hits_db_chain(seeded_db: AsyncSession) -> None:
    """DB 链命中：来源定位到 chunk，结果带 doc_id + 分数。"""
    refs = await knowledge_service.retrieve("退货政策是什么", TENANT, db=seeded_db)
    assert refs and all(ref["doc_id"] and "#" in str(ref["source"]) for ref in refs)


async def test_retrieve_governance(seeded_db: AsyncSession) -> None:
    """治理：跨租户 0 召回；过期不可见；机密对 cs 不可见、对 kb 可见。"""
    isolation = await knowledge_service.retrieve("他租户退货政策", TENANT, db=seeded_db)
    assert all(ref["title"] != "他租户退货" for ref in isolation)
    expired_hits = await knowledge_service.retrieve("已下线的旧退货政策全文", TENANT, db=seeded_db)
    assert all(ref["title"] != "过期政策" for ref in expired_hits)
    cs_hits = await knowledge_service.retrieve("内部成本价目表", TENANT, db=seeded_db, roles=["cs"])
    assert all(ref["title"] != "机密定价" for ref in cs_hits)
    kb_hits = await knowledge_service.retrieve("内部成本价目表", TENANT, db=seeded_db, roles=["kb"])
    assert any(ref["title"] == "机密定价" for ref in kb_hits)


async def test_retrieve_diversity_and_reject(seeded_db: AsyncSession) -> None:
    """多样性：同 doc 至多 2 块；无据拒答空列表（answer 层转 2001）。"""
    refs = await knowledge_service.retrieve("退货", TENANT, db=seeded_db, top_k=10, threshold=0.0)
    per_doc: dict[str, int] = {}
    for ref in refs:
        key = str(ref["doc_id"])
        per_doc[key] = per_doc.get(key, 0) + 1
    assert all(count <= settings.RAG_DIVERSITY_PER_DOC for count in per_doc.values())
    assert await knowledge_service.retrieve("量子纠缠退火算法原理", TENANT, db=seeded_db) == []


async def test_answer_with_db_refs(
    seeded_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """answer(DB)：引用非空 + faithfulness 满分；无据抛 NoEvidenceError(2001 由端点转)。"""
    monkeypatch.setattr(settings, "LLM_ENABLED", False)
    set_current_user(CurrentUser(username="demo", tenant=TENANT, roles=["cs"]))
    try:
        result = await chat_service.answer("退货政策是什么", db=seeded_db, roles=["cs"])
        assert result["references"] and result["faithfulness"] == 1.0
        assert result["degraded"] is True and result["trace_id"]
    finally:
        set_current_user(None)
    set_current_user(CurrentUser(username="demo", tenant=TENANT, roles=["cs"]))
    try:
        with pytest.raises(chat_service.NoEvidenceError):
            await chat_service.answer("量子纠缠退火算法原理", db=seeded_db, roles=["cs"])
    finally:
        set_current_user(None)


async def test_reindex_rebuilds_chunks(
    seeded_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reindex：删块后重建回满血并落 task done。"""
    from sqlalchemy import delete, func, select

    from app.db.models import KbChunk
    from app.services import task_service

    monkeypatch.setattr(settings, "SEED_TENANT", TENANT)
    await seeded_db.execute(delete(KbChunk))
    await seeded_db.commit()
    stats = await document_service.rebuild_chunks(seeded_db, tenant=TENANT)
    assert stats["docs"] >= 29 and stats["chunks"] >= stats["docs"]
    remaining = (await seeded_db.execute(select(func.count()).select_from(KbChunk))).scalar_one()
    assert int(remaining) == stats["chunks"]
    task = await task_service.create_task(
        db=seeded_db, tenant=TENANT, username="demo", type="kb.reindex", payload={}
    )
    marked = await task_service.mark_task(
        db=seeded_db,
        tenant=TENANT,
        task_id=task.id,
        status="done",
        progress=1.0,
        output=stats,
    )
    assert marked.status == "done" and marked.progress == 1.0
