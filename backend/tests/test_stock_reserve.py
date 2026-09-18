"""库存预占并发零超卖测试（对齐数据模型文档 §4 闸门键 + API 规范 §4.7 预占三端点）

链路：reserve_service（reserve/release/confirm）→ core/cache 闸门（stock:{tenant}:{warehouse}:{sku}）
      + inventory 表（reserved/qty 双写）+ stock_moves（确认扣减留痕）+ inventory_service.sync_gate 自愈。

覆盖：
- 闸门原子性：并发 50 次抢 10 件，恰好放行 10 次（不依赖 DB）。
- 服务层并发：20 个会话并发预占 1 件（库存 10），成功恰好 10、失败全 3004、终态账实不超发。
- 生命周期：reserve 5 → release 3 → confirm 2，账实与 kind="out" 流水落行。
- 边界：超量释放 3004、可确认预占不足 3004，失败不动账。
- 闸门自愈：入库后 sync_gate 对齐，新增库存可被预占。

本地无 Redis 服务也全绿：用例把 REDIS_URL 指向不可达端口，走「首败即 sticky 降级」真实路径。
运行（backend/ 目录）：pytest tests/test_stock_reserve.py
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core import cache
from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.models import Inventory, Product, Sku, Warehouse
from app.db.session import get_engine, init_models
from app.services import inventory_service, reserve_service

TENANT = settings.SEED_TENANT
SEED_QTY = 10  # 夹具库存行初值：qty=10 / reserved=0（并发口径的可预期基数）


def _tune_sqlite(engine) -> None:
    """并发写兜底（仅测试夹具，不动 app/db/session.py）。

    SQLite 无行锁（`with_for_update` 是空操作），且 WAL 下「先读后写」的升级会直接
    SQLITE_BUSY_SNAPSHOT；故测试库把每个写事务提到 `BEGIN IMMEDIATE` 串行化，
    复现 PG 上 `SELECT ... FOR UPDATE` 的行锁语义（生产 PG 无需此设置）。
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_conn, _record) -> None:
        dbapi_conn.isolation_level = None  # 交给下面 begin 事件显式发 BEGIN
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _begin_immediate(conn) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条用例前后清闸门粘性；REDIS_URL 指向不可达端口，确定性走内存降级路径。"""
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    cache.reset()
    yield
    cache.reset()


@pytest.fixture
async def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict]:
    """独立临时库 + 一条 qty=10 的库存行；并发用例按需以 factory 开多会话。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'stock.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    engine = get_engine()
    _tune_sqlite(engine)
    await init_models()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        product = Product(tenant=TENANT, spu_no="SPU-RSV", name="预占测试商品")
        session.add(product)
        await session.flush()
        sku = Sku(
            tenant=TENANT,
            product_id=product.id,
            color="白",
            size="M",
            list_price=10000,
            sale_price=9900,
        )
        session.add(sku)
        await session.flush()
        center = Warehouse(tenant=TENANT, name="预占测试仓")
        session.add(center)
        await session.flush()
        session.add(
            Inventory(
                tenant=TENANT,
                warehouse_id=center.id,
                sku_id=sku.id,
                qty=SEED_QTY,
                warn_line=3,
            )
        )
        await session.commit()
        env = {"factory": factory, "warehouse_id": center.id, "sku_id": sku.id}
    yield env


@pytest.fixture
async def db(env: dict) -> AsyncIterator[AsyncSession]:
    """顺序用例共用的单会话。"""
    async with env["factory"]() as session:
        yield session


def _args(env: dict) -> dict:
    """预占三函数共用的定位参数（租户 + 仓 + SKU）。"""
    return {"tenant": TENANT, "warehouse_id": env["warehouse_id"], "sku_id": env["sku_id"]}


async def _row(db: AsyncSession, env: dict) -> Inventory:
    row = await inventory_service.get_row(db, TENANT, env["warehouse_id"], env["sku_id"])
    assert row is not None
    return row


async def test_gate_concurrent_no_oversell() -> None:
    """闸门原子性：10 件被并发抢 50 次，恰好放行 10 次（闸门是零超卖第一道防线）。"""
    key = inventory_service.stock_key(TENANT, "wh-1", "sku-1")

    async def grab() -> bool:
        await asyncio.sleep(0)  # 让出控制权，最大化任务交错
        return await cache.stock_reserve(key, 1, base_available=10)

    results = await asyncio.gather(*(grab() for _ in range(50)))
    assert sum(results) == 10


async def test_concurrent_reserve_no_oversell(env: dict) -> None:
    """服务层并发：20 个会话各预占 1 件，成功恰好 10、失败全 3004、终态 reserved=10/available=0。"""
    factory = env["factory"]

    async def grab() -> str:
        async with factory() as session:
            try:
                await reserve_service.reserve_capacity(
                    session, **_args(env), qty=1, order_ref="SO-C", actor="tester"
                )
                return "ok"
            except BusinessError as exc:
                return f"err{exc.code}"

    results = await asyncio.gather(*(grab() for _ in range(20)))
    assert results.count("ok") == 10
    assert set(results) == {"ok", f"err{ErrorCode.STOCK_SHORTAGE}"}

    async with factory() as session:
        row = await _row(session, env)
        assert (row.qty, row.reserved) == (SEED_QTY, SEED_QTY)
        assert inventory_service.available_of(row) == 0


async def test_reserve_release_confirm_lifecycle(db: AsyncSession, env: dict) -> None:
    """生命周期：reserve 5 → release 3 → confirm 2，账实逐笔对得上且确认扣减留 out 流水。"""
    reserved = await reserve_service.reserve_capacity(
        db, **_args(env), qty=5, order_ref="SO-1", actor="tester"
    )
    assert (reserved["reserved"], reserved["available"]) == (5, 5)

    released = await reserve_service.release_reserve(
        db, **_args(env), qty=3, order_ref="SO-1", actor="tester"
    )
    assert (released["reserved"], released["available"]) == (2, 8)

    confirmed = await reserve_service.confirm_reserve(
        db, **_args(env), qty=2, order_ref="SO-1", actor="tester"
    )
    assert (confirmed["qty_after"], confirmed["reserved"], confirmed["available"]) == (8, 0, 8)

    moves = await inventory_service.list_moves(db, tenant=TENANT, sku_id=env["sku_id"])
    out = [m for m in moves if m.kind == "out"]
    assert len(out) == 1
    assert out[0].delta == -2 and out[0].order_ref == "SO-1"


async def test_release_and_confirm_shortage(db: AsyncSession, env: dict) -> None:
    """边界：超量释放 3004、可确认预占不足 3004，且失败不动作账面。"""
    await reserve_service.reserve_capacity(
        db, **_args(env), qty=2, order_ref="SO-2", actor="tester"
    )

    with pytest.raises(BusinessError) as over:
        await reserve_service.release_reserve(db, **_args(env), qty=3, actor="tester")
    assert over.value.code == ErrorCode.STOCK_SHORTAGE

    with pytest.raises(BusinessError) as bad:
        await reserve_service.confirm_reserve(db, **_args(env), qty=3, actor="tester")
    assert bad.value.code == ErrorCode.STOCK_SHORTAGE

    row = await _row(db, env)
    assert (row.qty, row.reserved) == (SEED_QTY, 2)


async def test_gate_selfheal_after_inbound(db: AsyncSession, env: dict) -> None:
    """闸门自愈：入库后 sync_gate 把闸门对齐到 DB 真值，新增库存立即可预占（防停在旧可用量）。"""
    await reserve_service.reserve_capacity(db, **_args(env), qty=SEED_QTY, order_ref="SO-3")
    with pytest.raises(BusinessError) as full:
        await reserve_service.reserve_capacity(db, **_args(env), qty=1)
    assert full.value.code == ErrorCode.STOCK_SHORTAGE  # 闸门已占满

    await inventory_service.move_stock(
        db,
        tenant=TENANT,
        kind="in",
        warehouse_id=env["warehouse_id"],
        sku_id=env["sku_id"],
        delta=5,
        reason="补货入库",
        actor="tester",
    )
    refilled = await reserve_service.reserve_capacity(db, **_args(env), qty=5, order_ref="SO-4")
    assert (refilled["reserved"], refilled["available"]) == (SEED_QTY + 5, 0)
    with pytest.raises(BusinessError) as again:
        await reserve_service.reserve_capacity(db, **_args(env), qty=1)
    assert again.value.code == ErrorCode.STOCK_SHORTAGE  # 闸门数量也随入库更新为 15
