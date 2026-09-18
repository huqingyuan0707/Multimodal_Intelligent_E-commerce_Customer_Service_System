"""B 端二期与风控单测（采购状态机 / 日结差异 / 风控复核，对齐 API 规范 §4.7/§4.8）

覆盖：
- 采购：驳回空理由 1001、非法流转 3005、驳回为终态、跨租户单 404、SKU 跨租户 404、
  数量非法 1001、未指定收货仓质检 1001；合格才写 inventory + stock_moves、不合格不入库；
- 财务：差异公式（应收-退款-扣点+运费）与 diff_warn 阈值、重复日结 1001、无单 404；
- 风控：拦截空理由 1001、重复复核 3005、放行/拦截均留 reviewer 与审计且不改用户状态。
运行（backend/ 目录）：pytest tests/test_biz_ops.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.models import (
    AuditLog,
    FinanceBill,
    Inventory,
    Product,
    PurchaseOrder,
    RiskEvent,
    Sku,
    StockMove,
    Warehouse,
)
from app.db.session import get_engine, init_models
from app.services import finance_service, procurement_service, risk_service, supplier_service

TENANT = settings.SEED_TENANT
OTHER_TENANT = "other-tenant"


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库（与 test_approvals.py 同口径，不灌演示数据，各域数据现建）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'bizops.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session


async def _sku(db: AsyncSession, *, tenant: str = TENANT, suffix: str = "") -> Sku:
    """建商品 + SKU（采购行快照取自 SKU 与服务端商品名）。"""
    product = Product(tenant=tenant, spu_no=f"SPU{suffix or '001'}", name=f"重磅纯棉短袖{suffix}")
    db.add(product)
    await db.flush()
    sku = Sku(
        tenant=tenant,
        product_id=product.id,
        color="米白",
        size="M",
        list_price=29900,
        sale_price=25900,
    )
    db.add(sku)
    await db.flush()
    return sku


async def _warehouse(db: AsyncSession, *, tenant: str = TENANT, name: str = "中心仓") -> Warehouse:
    row = Warehouse(tenant=tenant, name=name)
    db.add(row)
    await db.flush()
    return row


async def _draft(
    db: AsyncSession, *, supplier_id: str, warehouse_id: str, sku: Sku, qty: int = 10
) -> PurchaseOrder:
    """建一张草稿采购单（数量/单价按参数）。"""
    return await procurement_service.create_purchase_order(
        db,
        tenant=TENANT,
        supplier_id=supplier_id,
        warehouse_id=warehouse_id,
        lines=[{"sku_id": sku.id, "qty": qty, "price": 8800}],
        eta="2026-10-01",
        actor="ops1",
    )


async def _approved_flow(db: AsyncSession) -> tuple[PurchaseOrder, Warehouse, Sku]:
    """备齐供应商/仓/SKU 并推进到「已审批」，返回采购单。"""
    supplier = await supplier_service.create_supplier(
        db, tenant=TENANT, name="杭州锦棉纺织", pay_terms="月结 30 天", pass_rate=0.98
    )
    warehouse = await _warehouse(db)
    sku = await _sku(db)
    order = await _draft(db, supplier_id=supplier.id, warehouse_id=warehouse.id, sku=sku)
    await procurement_service.approve_purchase_order(
        db, tenant=TENANT, order_id=order.id, approved=True, actor="boss"
    )
    return order, warehouse, sku


# ---------------- 采购 ----------------


async def test_reject_requires_reason_and_is_final(db: AsyncSession) -> None:
    """驳回理由必填（1001）；驳回为终态，再审批/到货一律 3005。"""
    supplier = await supplier_service.create_supplier(db, tenant=TENANT, name="苏州云锦制衣")
    warehouse = await _warehouse(db)
    sku = await _sku(db)
    order = await _draft(db, supplier_id=supplier.id, warehouse_id=warehouse.id, sku=sku)

    with pytest.raises(BusinessError) as exc:
        await procurement_service.approve_purchase_order(
            db, tenant=TENANT, order_id=order.id, approved=False, reason="  ", actor="boss"
        )
    assert exc.value.code == ErrorCode.PARAM_INVALID

    rejected = await procurement_service.approve_purchase_order(
        db, tenant=TENANT, order_id=order.id, approved=False, reason="报价高于市场价", actor="boss"
    )
    assert rejected.status == "rejected"
    assert rejected.qc_note == "报价高于市场价"
    with pytest.raises(BusinessError) as exc2:
        await procurement_service.receive_purchase_order(
            db, tenant=TENANT, order_id=order.id, actor="ops1"
        )
    assert exc2.value.code == ErrorCode.ORDER_STATE_ILLEGAL


async def test_illegal_transition_and_cross_tenant(db: AsyncSession) -> None:
    """草稿不能直接到货/质检（3005）；跨租户取单 404。"""
    supplier = await supplier_service.create_supplier(db, tenant=TENANT, name="东莞恒丰辅料")
    warehouse = await _warehouse(db)
    sku = await _sku(db)
    order = await _draft(db, supplier_id=supplier.id, warehouse_id=warehouse.id, sku=sku)

    with pytest.raises(BusinessError) as exc:
        await procurement_service.receive_purchase_order(
            db, tenant=TENANT, order_id=order.id, actor="ops1"
        )
    assert exc.value.code == ErrorCode.ORDER_STATE_ILLEGAL
    with pytest.raises(BusinessError) as exc2:
        await procurement_service.qc_purchase_order(
            db, tenant=TENANT, order_id=order.id, passed=True, note="全检合格", actor="qc1"
        )
    assert exc2.value.code == ErrorCode.ORDER_STATE_ILLEGAL
    with pytest.raises(BusinessError) as exc3:
        await procurement_service.approve_purchase_order(
            db, tenant=OTHER_TENANT, order_id=order.id, approved=True, actor="boss"
        )
    assert exc3.value.code == ErrorCode.NOT_FOUND


async def test_create_rejects_bad_lines_and_warehouse(db: AsyncSession) -> None:
    """建单校验：SKU 跨租户 404、数量非法 1001、收货仓不存在 404、行名由服务端快照。"""
    supplier = await supplier_service.create_supplier(db, tenant=TENANT, name="杭州锦棉纺织")
    warehouse = await _warehouse(db)
    sku = await _sku(db)
    other_sku = await _sku(db, tenant=OTHER_TENANT, suffix="999")

    with pytest.raises(BusinessError) as exc:
        await _draft(db, supplier_id=supplier.id, warehouse_id=warehouse.id, sku=other_sku)
    assert exc.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(BusinessError) as exc2:
        await _draft(db, supplier_id=supplier.id, warehouse_id=warehouse.id, sku=sku, qty=0)
    assert exc2.value.code == ErrorCode.PARAM_INVALID
    with pytest.raises(BusinessError) as exc3:
        await _draft(db, supplier_id=supplier.id, warehouse_id="no-such-wh", sku=sku)
    assert exc3.value.code == ErrorCode.NOT_FOUND

    order = await _draft(db, supplier_id=supplier.id, warehouse_id=warehouse.id, sku=sku)
    data = procurement_service.purchase_to_dict(order, supplier_name=supplier.name)
    assert data["status"] == "draft"
    assert data["allowed_actions"] == ["approve"]
    assert data["qty_total"] == 10
    assert data["amount"] == 88000
    # 行名/颜色/尺码全部服务端快照，前端传什么都不影响
    assert data["items"][0]["name"] == "重磅纯棉短袖"
    assert data["items"][0]["color"] == "米白"


async def test_qc_pass_writes_stock(db: AsyncSession) -> None:
    """质检合格：写 inventory + stock_moves 并置 stocked（审批前不动账）。"""
    order, warehouse, sku = await _approved_flow(db)
    before = (await db.execute(select(func.count()).select_from(StockMove))).scalar_one()
    assert before == 0

    await procurement_service.receive_purchase_order(
        db, tenant=TENANT, order_id=order.id, eta="2026-09-20", actor="ops1"
    )
    stocked = await procurement_service.qc_purchase_order(
        db, tenant=TENANT, order_id=order.id, passed=True, note="抽检合格", actor="qc1"
    )
    assert stocked.status == "stocked"
    assert stocked.qc_result == "pass"
    assert procurement_service.purchase_to_dict(stocked)["allowed_actions"] == []

    inv = (
        await db.execute(
            select(Inventory).where(
                Inventory.tenant == TENANT,
                Inventory.warehouse_id == warehouse.id,
                Inventory.sku_id == sku.id,
            )
        )
    ).scalar_one()
    assert inv.qty == 10
    moves = (await db.execute(select(StockMove).where(StockMove.order_ref == order.id))).scalars()
    assert [move.delta for move in moves] == [10]
    audits = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "purchase.qc")
        )
    ).scalar_one()
    assert audits == 1


async def test_qc_fail_returns_without_stock(db: AsyncSession) -> None:
    """质检不合格：置 returned 且不进库存；质检说明必填（1001）。"""
    order, _, _ = await _approved_flow(db)
    await procurement_service.receive_purchase_order(
        db, tenant=TENANT, order_id=order.id, actor="ops1"
    )

    with pytest.raises(BusinessError) as exc:
        await procurement_service.qc_purchase_order(
            db, tenant=TENANT, order_id=order.id, passed=False, note=" ", actor="qc1"
        )
    assert exc.value.code == ErrorCode.PARAM_INVALID

    returned = await procurement_service.qc_purchase_order(
        db, tenant=TENANT, order_id=order.id, passed=False, note="线头密度不合格", actor="qc1"
    )
    assert returned.status == "returned"
    assert returned.qc_result == "fail"
    count = (await db.execute(select(func.count()).select_from(Inventory))).scalar_one()
    assert count == 0


async def test_qc_requires_warehouse(db: AsyncSession) -> None:
    """未指定收货仓的单在质检合格时被拒（1001，不允许凭空入库）。"""
    supplier = await supplier_service.create_supplier(db, tenant=TENANT, name="杭州锦棉纺织")
    sku = await _sku(db)
    order = await _draft(db, supplier_id=supplier.id, warehouse_id="", sku=sku)
    await procurement_service.approve_purchase_order(
        db, tenant=TENANT, order_id=order.id, approved=True, actor="boss"
    )
    await procurement_service.receive_purchase_order(
        db, tenant=TENANT, order_id=order.id, actor="ops1"
    )
    with pytest.raises(BusinessError) as exc:
        await procurement_service.qc_purchase_order(
            db, tenant=TENANT, order_id=order.id, passed=True, note="全检合格", actor="qc1"
        )
    assert exc.value.code == ErrorCode.PARAM_INVALID
    count = (await db.execute(select(func.count()).select_from(Inventory))).scalar_one()
    assert count == 0


async def test_list_filter_illegal_status(db: AsyncSession) -> None:
    """采购单列表：非法状态筛选 1001；合法状态筛得准。"""
    order, _, _ = await _approved_flow(db)
    with pytest.raises(BusinessError) as exc:
        await procurement_service.list_purchase_orders(db, tenant=TENANT, status="paid")
    assert exc.value.code == ErrorCode.PARAM_INVALID

    listed = await procurement_service.list_purchase_orders(db, tenant=TENANT, status="approved")
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == order.id
    assert listed["items"][0]["supplier_name"] == "杭州锦棉纺织"


# ---------------- 财务 ----------------


async def _bill(db: AsyncSession, *, biz_date: str, diff: int) -> FinanceBill:
    """按目标差异造日结单：expected 固定 100000 分，received = expected + diff。"""
    row = FinanceBill(
        tenant=TENANT,
        biz_date=biz_date,
        receivable=120000,
        refund=10000,
        fee=12000,
        freight=2000,
        received=100000 + diff,
    )
    db.add(row)
    await db.commit()
    return row


async def test_diff_formula_and_warn(db: AsyncSession) -> None:
    """差异公式唯一：expected = 应收-退款-扣点+运费；超阈值才红字。"""
    small = await _bill(db, biz_date="2026-09-16", diff=120)
    big = await _bill(db, biz_date="2026-09-17", diff=-6000)

    data = await finance_service.list_bills(db, tenant=TENANT)
    assert data["diff_warn_cents"] == settings.FINANCE_DIFF_WARN_CENTS
    assert data["total"] == 2
    by_date = {item["biz_date"]: item for item in data["items"]}
    assert by_date["2026-09-16"]["expected"] == 100000
    assert by_date["2026-09-16"]["diff"] == 120
    assert by_date["2026-09-16"]["diff_warn"] is False
    assert by_date["2026-09-17"]["diff"] == -6000
    assert by_date["2026-09-17"]["diff_warn"] is True
    assert data["unsettled"] == 2
    assert finance_service.bill_to_dict(small)["settled"] is False
    assert finance_service.bill_to_dict(big)["settled"] is False


async def test_settle_once_and_missing(db: AsyncSession) -> None:
    """日结确认幂等红线：重复确认 1001，账单不存在 404，确认人落库并记审计。"""
    await _bill(db, biz_date="2026-09-17", diff=0)
    with pytest.raises(BusinessError) as exc:
        await finance_service.settle(db, tenant=TENANT, biz_date="2026-09-15", actor="fin1")
    assert exc.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(BusinessError) as exc2:
        await finance_service.settle(db, tenant=TENANT, biz_date="2026-9-17", actor="fin1")
    assert exc2.value.code == ErrorCode.PARAM_INVALID

    done = await finance_service.settle(db, tenant=TENANT, biz_date="2026-09-17", actor="fin1")
    assert done.settled_by == "fin1"
    with pytest.raises(BusinessError) as exc3:
        await finance_service.settle(db, tenant=TENANT, biz_date="2026-09-17", actor="fin2")
    assert exc3.value.code == ErrorCode.PARAM_INVALID
    audits = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "finance.settle")
        )
    ).scalar_one()
    assert audits == 1


# ---------------- 风控 ----------------


async def _event(db: AsyncSession, *, user_ref: str = "buyer-9527") -> RiskEvent:
    row = RiskEvent(
        tenant=TENANT,
        user_ref=user_ref,
        kind="refund_abuse",
        detail='{"device_shared": 3, "refund_30d": 9}',
    )
    db.add(row)
    await db.commit()
    return row


async def test_review_block_requires_reason_and_is_once(db: AsyncSession) -> None:
    """拦截理由必填（1001）；复核后重复处理 3005；复核只落结论不改用户状态。"""
    row = await _event(db)
    with pytest.raises(BusinessError) as exc:
        await risk_service.review_event(
            db, tenant=TENANT, event_id=row.id, block=True, reason="   ", reviewer="sec1"
        )
    assert exc.value.code == ErrorCode.PARAM_INVALID

    blocked = await risk_service.review_event(
        db,
        tenant=TENANT,
        event_id=row.id,
        block=True,
        reason="同设备 30 天退款 9 次",
        reviewer="sec1",
    )
    assert blocked.status == "blocked"
    assert blocked.reviewer == "sec1"
    data = risk_service.event_to_dict(blocked)
    assert data["status_label"] == "已拦截"
    assert data["kind_label"] == "退款异常"
    assert data["reviewable"] is False
    assert data["detail"]["refund_30d"] == 9

    with pytest.raises(BusinessError) as exc2:
        await risk_service.review_event(
            db, tenant=TENANT, event_id=row.id, block=False, reviewer="sec2"
        )
    assert exc2.value.code == ErrorCode.ORDER_STATE_ILLEGAL
    audits = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "risk.block")
        )
    ).scalar_one()
    assert audits == 1


async def test_review_pass_and_list_filter(db: AsyncSession) -> None:
    """放行可不填理由；列表按状态筛选并给出待复核数；跨租户复核 404。"""
    first = await _event(db, user_ref="buyer-0001")
    second = await _event(db, user_ref="buyer-0002")
    await risk_service.review_event(
        db, tenant=TENANT, event_id=second.id, block=False, reviewer="sec1"
    )

    pending = await risk_service.list_events(db, tenant=TENANT, status="pending")
    assert pending["total"] == 1
    assert pending["pending"] == 1
    assert pending["items"][0]["id"] == first.id
    with pytest.raises(BusinessError) as exc:
        await risk_service.list_events(db, tenant=TENANT, status="frozen")
    assert exc.value.code == ErrorCode.PARAM_INVALID

    passed = await risk_service.list_events(db, tenant=TENANT, status="passed")
    assert passed["total"] == 1
    assert passed["items"][0]["reason"] == ""
    with pytest.raises(BusinessError) as exc2:
        await risk_service.review_event(
            db, tenant=OTHER_TENANT, event_id=first.id, block=False, reviewer="sec9"
        )
    assert exc2.value.code == ErrorCode.NOT_FOUND
