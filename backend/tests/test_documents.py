"""知识库文档单测（种子解析 + 详情/编辑/删除，对齐 FR-13 + API 规范 §4.4）

覆盖：front-matter 解析（标题/密级/渠道/生效期/正文去注释）；详情跨租户 404；
编辑内容变版本 +1、撞他篇 1001、非法密级 1001；种子 29 篇幂等（二次 False）。
运行（backend/ 目录）：pytest tests/test_documents.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db import seed as seed_mod
from app.db import session as session_mod
from app.db.session import get_engine, init_models
from app.services import document_service

TENANT = "kb-test-tenant"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（引擎单例夹具后还原）。"""
    monkeypatch.setattr(
        session_mod.settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'kb.db'}"
    )
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


def test_parse_seed_markdown() -> None:
    """真实种子 01：标题/密级/渠道/生效期/正文去注释行。"""
    text = (ROOT / "docs" / "knowledge-base" / "01-女装尺码对照与选码.md").read_text(
        encoding="utf-8"
    )
    meta = document_service.parse_seed_markdown(text)
    assert meta["title"] == "女装尺码对照与选码"
    assert meta["security_level"] == "public"
    assert meta["channels"] == ["all"]
    assert meta["valid_from"] is not None and meta["valid_to"] is not None
    assert "政策口径" in meta["body"] and "<!--" not in meta["body"]


async def test_crud_detail_update_delete(db: AsyncSession) -> None:
    row, skipped = await document_service.get_or_create_doc(
        db, tenant=TENANT, title="退换政策", content="七天无理由", raw=b"seven"
    )
    assert skipped is False
    detail = document_service.detail_to_dict(
        await document_service.get_doc(db, tenant=TENANT, doc_id=row.id)
    )
    assert detail["content"] == "七天无理由" and detail["channels"] == ["all"]
    try:
        await document_service.get_doc(db, tenant="other-tenant", doc_id=row.id)
        raise AssertionError("跨租户应 404")
    except BusinessError as exc:
        assert exc.code == ErrorCode.NOT_FOUND
    updated = await document_service.update_doc(
        db,
        tenant=TENANT,
        doc_id=row.id,
        title="退换政策 v2",
        content="七天无理由+运费险",
        security_level="public",
        channels=["all"],
    )
    assert updated.version == 2 and updated.security_level == "public"
    other, _ = await document_service.get_or_create_doc(
        db, tenant=TENANT, title="另一篇", content="独立内容", raw=b"other"
    )
    try:
        await document_service.update_doc(
            db,
            tenant=TENANT,
            doc_id=other.id,
            title="另一篇",
            content="七天无理由+运费险",
            security_level="public",
            channels=["all"],
        )
        raise AssertionError("撞内容应 1001")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    try:
        await document_service.update_doc(
            db,
            tenant=TENANT,
            doc_id=row.id,
            title="x",
            content="y",
            security_level="绝密",
            channels=["all"],
        )
        raise AssertionError("非法密级应 1001")
    except BusinessError as exc:
        assert exc.code == ErrorCode.PARAM_INVALID
    await document_service.delete_doc(db, tenant=TENANT, doc_id=other.id)
    assert await document_service.count_docs(db, tenant=TENANT) == 1


async def test_kb_seed_idempotent(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """种子 29 篇全量 + 二次幂等；种子租户走测试租户隔离生产数据。"""
    monkeypatch.setattr(settings, "KB_SEED_DEMO", True)
    monkeypatch.setattr(settings, "KB_SEED_DIR", str(ROOT / "docs" / "knowledge-base"))
    monkeypatch.setattr(settings, "SEED_TENANT", TENANT)
    assert await seed_mod.ensure_kb_seed(db) is True
    assert await document_service.count_docs(db, tenant=TENANT) == 29
    assert await seed_mod.ensure_kb_seed(db) is False
