"""B 端服务层单测（商品/库存/订单/审批，对齐数据模型文档 §2.1 + API 规范 §4.7）

红线口径逐一验证：
- 改价恒进审批（未批不改价）；审批不可重复处理。
- available = qty - reserved - locked 唯一口径；出库不足 3004；调拨拆两行流水。
- 盘点差异不自动改账，批准后生效。
- 状态机：仅「待发货」可发货（3005）；物流单号格式校验（1001）。
- 退款超阈值转审批；退款金额与订单不一致拒绝执行。
- B2B_SEED_DEMO 幂等（已有商品即跳过）。
运行（backend/ 目录）：pytest tests/test_b2b_services.py
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.db import session as session_mod
from app.db.models import Inventory, KbChunk, KbDoc, Product, SalesOrder, Sku, StockMove, Warehouse
from app.db.seed import ensure_b2b_demo
from app.db.session import get_engine, init_models
from app.services import (
    approval_service,
    goods_service,
    inventory_service,
    logistics_service,
    order_service,
    promo_service,
    review_service,
)

TENANT = settings.SEED_TENANT


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
    """独立临时库 + 灌 B 端演示数据（引擎单例在夹具结束后自动还原）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'b2b.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        assert await ensure_b2b_demo(session) is True
        yield session


async def _sku(db: AsyncSession, spu_no: str, color: str, size: str) -> Sku:
    product = (await db.execute(select(Product).where(Product.spu_no == spu_no))).scalar_one()
    return (
        await db.execute(
            select(Sku).where(Sku.product_id == product.id, Sku.color == color, Sku.size == size)
        )
    ).scalar_one()


async def _order(db: AsyncSession, outer_id: str) -> SalesOrder:
    return (
        await db.execute(select(SalesOrder).where(SalesOrder.outer_id == outer_id))
    ).scalar_one()


async def _wh(db: AsyncSession, name: str) -> Warehouse:
    return (
        await db.execute(
            select(Warehouse).where(Warehouse.tenant == TENANT, Warehouse.name == name)
        )
    ).scalar_one()


async def _inv(db: AsyncSession, warehouse_id: str, sku_id: str) -> Inventory:
    return (
        await db.execute(
            select(Inventory).where(
                Inventory.tenant == TENANT,
                Inventory.warehouse_id == warehouse_id,
                Inventory.sku_id == sku_id,
            )
        )
    ).scalar_one()


async def test_seed_idempotent_and_stock_math(db: AsyncSession) -> None:
    """种子幂等；available/warning 口径在 stock_table 一次算好（演示行 6-2=4 < 10）。"""
    assert await ensure_b2b_demo(db) is False
    data = await inventory_service.stock_table(db, tenant=TENANT, only_warn=True, size=200)
    white_m = [i for i in data["items"] if i["sku_code"] == "TSIRT-001-白-M"]
    center_rows = [i for i in white_m if i["warehouse"] == "中心仓"]
    assert center_rows and center_rows[0]["available"] == 4
    assert center_rows[0]["warning"] is True
    goods = await goods_service.list_goods(db, tenant=TENANT)
    assert goods["total"] == 2  # T 恤 + 卫衣
    assert goods["items"][0]["attrs"]["材质"]  # 扩展属性给 workbench 属性卡


async def test_seed_disabled_by_settings(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """B2B_SEED_DEMO=false（生产口径）不再灌演示数据。"""
    monkeypatch.setattr(settings, "B2B_SEED_DEMO", False)
    assert await ensure_b2b_demo(db) is False


async def test_price_change_needs_approval(db: AsyncSession) -> None:
    """改价红线：提交只生成审批单（价格不动），批准才生效，且不可重复处理。"""
    sku = await _sku(db, "TSIRT-001", "白", "M")
    old_price = sku.sale_price
    approval = await goods_service.submit_price_change(
        db,
        tenant=TENANT,
        sku_id=sku.id,
        new_price=11900,
        reason="大促报名",
        applicant="tester",
    )
    assert approval.status == "pending"
    assert old_price == 12900  # 防呆：演示数据原价确为 129 元
    after = (await db.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    assert after.sale_price == old_price  # 未批不改价

    with pytest.raises(BusinessError) as bad:
        await goods_service.submit_price_change(
            db, tenant=TENANT, sku_id=sku.id, new_price=0, reason="x", applicant="tester"
        )
    assert bad.value.code == ErrorCode.PARAM_INVALID

    decided = await approval_service.decide(
        db, tenant=TENANT, approval_id=approval.id, approve=True, approver="boss"
    )
    assert decided.status == "approved"
    applied = (await db.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    assert applied.sale_price == 11900
    with pytest.raises(BusinessError) as twice:
        await approval_service.decide(
            db, tenant=TENANT, approval_id=approval.id, approve=True, approver="boss"
        )
    assert twice.value.code == ErrorCode.APPROVAL_DENIED


async def test_goods_change_syncs_knowledge(db: AsyncSession) -> None:
    """FR-10.1 知识同步：商品变更自动 upsert《商品知识｜SPU》一篇，版本递增不另开新篇。"""
    product = (await db.execute(select(Product).where(Product.spu_no == "TSIRT-001"))).scalar_one()
    sku = await _sku(db, "TSIRT-001", "白", "M")

    # 1) 上下架首变：创建知识文档，含面料/尺码/价格段，按 ## 分节切块
    _, kb1 = await goods_service.set_goods_status(
        db, tenant=TENANT, product_id=product.id, status="off", actor="tester"
    )
    assert kb1["version"] == 1 and kb1["title"].startswith("商品知识｜TSIRT-001")
    doc = (await db.execute(select(KbDoc).where(KbDoc.id == kb1["doc_id"]))).scalar_one()
    for section in ("面料成分", "尺码范围", "价格段", "SKU 明细"):
        assert section in doc.content
    assert "已下架" in doc.content  # 状态变更体现在正文
    chunks = list((await db.execute(select(KbChunk).where(KbChunk.doc_id == doc.id))).scalars())
    assert len(chunks) >= 3

    # 2) 二次变更：同一篇 version+1（按标题幂等），不产生第二篇
    _, kb2 = await goods_service.set_goods_status(
        db, tenant=TENANT, product_id=product.id, status="on", actor="tester"
    )
    assert kb2["doc_id"] == kb1["doc_id"] and kb2["version"] == 2
    same_title = list(
        (
            await db.execute(
                select(KbDoc).where(KbDoc.tenant == TENANT, KbDoc.title == kb1["title"])
            )
        ).scalars()
    )
    assert len(same_title) == 1

    # 3) 改条码：正文带新条码，版本继续递增
    _, kb3 = await goods_service.update_sku(
        db, tenant=TENANT, sku_id=sku.id, barcode="693001009", actor="tester"
    )
    assert kb3["version"] == 3
    refreshed = (await db.execute(select(KbDoc).where(KbDoc.id == kb1["doc_id"]))).scalar_one()
    assert "693001009" in refreshed.content

    # 4) 审批改价生效：价格段拿到新价（RAG 不答旧价）
    approval = await goods_service.submit_price_change(
        db, tenant=TENANT, sku_id=sku.id, new_price=11900, reason="大促报名", applicant="tester"
    )
    await approval_service.decide(
        db, tenant=TENANT, approval_id=approval.id, approve=True, approver="boss"
    )
    after_price = (await db.execute(select(KbDoc).where(KbDoc.id == kb1["doc_id"]))).scalar_one()
    assert "¥119.00" in after_price.content

    # 5) 列表口径：SKU 带 available、SPU 带 sales（矩阵/销量列数据源）
    goods = await goods_service.list_goods(db, tenant=TENANT)
    item = next(i for i in goods["items"] if i["spu_no"] == "TSIRT-001")
    assert isinstance(item["sales"], int)
    sku_m = next(s for s in item["skus"] if s["color"] == "白" and s["size"] == "M")
    assert isinstance(sku_m["available"], int) and sku_m["available"] >= 4


async def test_stock_out_shortage_and_transfer(db: AsyncSession) -> None:
    """出库超可用量 3004；调拨拆两行流水且总量守恒。"""
    sku = await _sku(db, "TSIRT-001", "白", "M")
    center, east = await _wh(db, "中心仓"), await _wh(db, "华东仓")
    before = (await _inv(db, center.id, sku.id)).qty + (await _inv(db, east.id, sku.id)).qty
    with pytest.raises(BusinessError) as short:
        await inventory_service.move_stock(
            db,
            tenant=TENANT,
            kind="out",
            warehouse_id=center.id,
            sku_id=sku.id,
            delta=999,
            reason="卖断货",
            actor="tester",
        )
    assert short.value.code == ErrorCode.STOCK_SHORTAGE
    result = await inventory_service.move_stock(
        db,
        tenant=TENANT,
        kind="move",
        warehouse_id=center.id,
        sku_id=sku.id,
        delta=1,
        reason="补华东仓",
        actor="tester",
        to_warehouse_id=east.id,
    )
    assert result["available"] == 3  # 6→5，reserved 2 → 5-2
    moves = await inventory_service.list_moves(db, tenant=TENANT, sku_id=sku.id)
    assert len(moves) == 2
    assert {m.delta for m in moves} == {-1, 1}
    after = (await _inv(db, center.id, sku.id)).qty + (await _inv(db, east.id, sku.id)).qty
    assert after == before  # 调拨不产生账实差


async def test_stocktake_diff_applies_only_after_approval(db: AsyncSession) -> None:
    """盘点差异不直接改账；批准后 qty 改为实盘并留 adjust 流水。"""
    sku = await _sku(db, "HOODIE-002", "米白", "M")
    center = await _wh(db, "中心仓")
    row = await _inv(db, center.id, sku.id)
    assert row.qty == 12
    result = await inventory_service.stocktake(
        db,
        tenant=TENANT,
        lines=[{"warehouse_id": center.id, "sku_id": sku.id, "counted": 10}],
        reason="季度盘点",
        actor="tester",
    )
    assert result["diff_count"] == 1
    assert (await _inv(db, center.id, sku.id)).qty == 12  # 未批不改账
    await approval_service.decide(
        db,
        tenant=TENANT,
        approval_id=result["approval_ids"][0],
        approve=True,
        approver="boss",
    )
    assert (await _inv(db, center.id, sku.id)).qty == 10
    adjust = (
        await db.execute(
            select(StockMove).where(StockMove.sku_id == sku.id, StockMove.kind == "adjust")
        )
    ).scalar_one()
    assert adjust.delta == -2


async def test_ship_state_machine_and_tracking(db: AsyncSession) -> None:
    """仅「待发货」可发货（3005）；单号非法 1001；成功发货后面单可查。"""
    pending = await _order(db, "DY20260912002")
    with pytest.raises(BusinessError) as illegal:
        await order_service.ship(
            db, tenant=TENANT, order_id=pending.id, company="顺丰", tracking_no="SF1234567890"
        )
    assert illegal.value.code == ErrorCode.ORDER_STATE_ILLEGAL

    paid = await _order(db, "TB20260912001")
    with pytest.raises(BusinessError) as bad_no:
        await order_service.ship(
            db, tenant=TENANT, order_id=paid.id, company="顺丰", tracking_no="SF 12!"
        )
    assert bad_no.value.code == ErrorCode.PARAM_INVALID
    with pytest.raises(BusinessError) as bad_co:
        await order_service.ship(
            db, tenant=TENANT, order_id=paid.id, company="宅急送", tracking_no="ZJS12345678"
        )
    assert bad_co.value.code == ErrorCode.PARAM_INVALID

    data = await order_service.ship(
        db, tenant=TENANT, order_id=paid.id, company="顺丰", tracking_no="SF1234567890"
    )
    assert data["status"] == "shipped"
    detail = await order_service.get_detail(db, tenant=TENANT, order_id=paid.id)
    assert detail["tracking_no"] == "SF1234567890"
    assert detail["allowed_actions"] == ["confirm", "aftersale"]


async def test_aftersale_refund_threshold(db: AsyncSession) -> None:
    """小额退款直接建单；超阈值转审批且金额与订单不符时拒绝执行。"""
    shipped = await _order(db, "WX20260911003")
    small = await order_service.create_aftersale(
        db,
        tenant=TENANT,
        order_id=shipped.id,
        reason="袖口线头",
        amount=100,
        trace_id="t-1",
        applicant="tester",
    )
    assert small["need_approval"] is False and small["status"] == "pending"

    big = await order_service.create_aftersale(
        db,
        tenant=TENANT,
        order_id=shipped.id,
        reason="整单退",
        amount=shipped.total,
        trace_id="t-2",
        applicant="tester",
        evidence=["photo-1.jpg"],
    )
    assert big["need_approval"] is True and big["status"] == "approving"
    assert big["approval_id"]

    # 篡改金额（大于订单总额）→ 批准时拒绝执行并整体回滚
    row = await approval_service.get_or_raise(db, TENANT, big["approval_id"])
    with pytest.raises(BusinessError) as tamper:
        await approval_service.decide(
            db,
            tenant=TENANT,
            approval_id=row.id,
            approve=True,
            approver="boss",
            modified_args={"amount": shipped.total + 1},
        )
    assert tamper.value.code == ErrorCode.ORDER_STATE_ILLEGAL

    await approval_service.decide(
        db, tenant=TENANT, approval_id=row.id, approve=True, approver="boss"
    )
    detail = await order_service.get_detail(db, tenant=TENANT, order_id=shipped.id)
    assert detail["status"] == "aftersale"
    assert [a["status"] for a in detail["aftersales"]].count("done") == 1


async def test_fieldfix_evidence_roundtrip(db: AsyncSession) -> None:
    """修复1：evidence 建单→列表→详情同一口径，不再丢失。"""
    shipped = await _order(db, "WX20260911003")
    proof = ["https://cdn/x/1.jpg", "https://cdn/x/2.jpg"]
    created = await order_service.create_aftersale(
        db,
        tenant=TENANT,
        order_id=shipped.id,
        reason="袖口脱线",
        amount=100,
        trace_id="t-ev",
        applicant="tester",
        evidence=proof,
    )
    listed = [
        d
        for d in (await order_service.list_aftersales(db, tenant=TENANT, size=100))["items"]
        if d["id"] == created["aftersale_id"]
    ]
    assert listed and listed[0]["evidence"] == proof
    detail = await order_service.get_detail(db, tenant=TENANT, order_id=shipped.id)
    nested = [a for a in detail["aftersales"] if a["id"] == created["aftersale_id"]]
    assert nested and nested[0]["evidence"] == proof
    assert nested[0]["order_id"] == shipped.id and nested[0]["status_label"]


async def test_fieldfix_promo_valid_dates(db: AsyncSession) -> None:
    """修复3：活动有效期落库可查；发券回 idem_key/created_at；非法日期 1001。"""
    row = await promo_service.create_promo(
        db,
        tenant=TENANT,
        name="秋促",
        budget=10,
        valid_from="2026-09-01 00:00:00",
        valid_to="2026-09-30 23:59:59",
    )
    promo = promo_service.promo_to_dict(row)
    assert promo["valid_from"] == "2026-09-01 00:00:00"
    assert promo["valid_to"] == "2026-09-30 23:59:59"
    granted, replayed = await promo_service.grant(
        db, tenant=TENANT, promo_id=row.id, user_ref="u1", idem_key="k-fieldfix-1"
    )
    assert replayed is False and granted["idem_key"] == "k-fieldfix-1"
    assert granted["created_at"] and "T" not in granted["created_at"]
    with pytest.raises(BusinessError) as bad_fmt:
        await promo_service.create_promo(
            db, tenant=TENANT, name="坏日期", budget=5, valid_from="9月1日"
        )
    assert bad_fmt.value.code == ErrorCode.PARAM_INVALID
    with pytest.raises(BusinessError) as bad_range:
        await promo_service.create_promo(
            db,
            tenant=TENANT,
            name="倒挂",
            budget=5,
            valid_from="2026-10-01 00:00:00",
            valid_to="2026-09-01 00:00:00",
        )
    assert bad_range.value.code == ErrorCode.PARAM_INVALID


async def test_fieldfix_logistics_and_time_format(db: AsyncSession) -> None:
    """修复2/4/5：公司名单统一 8 家；运单 status_label；时间空格秒口径。"""
    assert "申通" in order_service.COMPANIES and "德邦" in logistics_service.COMPANIES
    paid = await _order(db, "TB20260912001")
    shipped = await order_service.ship(
        db, tenant=TENANT, order_id=paid.id, company="顺丰", tracking_no="SF9999000011"
    )
    assert shipped["logistics_status"] == "created" and shipped["company"] == "顺丰"
    tracked = await logistics_service.track(db, tenant=TENANT, tracking_no="SF9999000011")
    assert tracked["id"] and tracked["status_label"] == "已创建"
    assert " " in tracked["created_at"] and "T" not in tracked["created_at"]
    review = await review_service.create_review(
        db, tenant=TENANT, platform="淘宝", outer_id="TB-1", level="bad", content="差"
    )
    review_dict = review_service.review_to_dict(review)
    assert "T" not in review_dict["created_at"]
    ticket, _ = await review_service.create_review_ticket(db, tenant=TENANT, review_id=review.id)
    ticket_dict = review_service.ticket_to_dict(ticket)
    assert "T" not in ticket_dict["created_at"] and "T" not in ticket_dict["sla_due"]


async def test_order_confirm_state_machine(db: AsyncSession) -> None:
    """FR-10.4 状态机「已发→签收→完成」：仅已发货可签收；签收后进 completed 且可建售后。"""
    with pytest.raises(BusinessError) as illegal:
        await order_service.confirm(
            db, tenant=TENANT, order_id=(await _order(db, "DY20260912002")).id
        )
    assert illegal.value.code == ErrorCode.ORDER_STATE_ILLEGAL

    paid = await _order(db, "TB20260912001")
    await order_service.ship(
        db, tenant=TENANT, order_id=paid.id, company="顺丰", tracking_no="SF8888000022"
    )
    detail = await order_service.get_detail(db, tenant=TENANT, order_id=paid.id)
    assert detail["allowed_actions"] == ["confirm", "aftersale"]

    done = await order_service.confirm(db, tenant=TENANT, order_id=paid.id)
    assert done["status"] == "completed" and done["allowed_actions"] == ["aftersale"]

    with pytest.raises(BusinessError) as again:
        await order_service.confirm(db, tenant=TENANT, order_id=paid.id)
    assert again.value.code == ErrorCode.ORDER_STATE_ILLEGAL


async def test_aftersale_dispose_restock(db: AsyncSession) -> None:
    """质检处置-二次入库：库存回补 + disposition=restocked + 幂等拒绝重复处置。"""
    shipped = await _order(db, "WX20260911003")
    created = await order_service.create_aftersale(
        db,
        tenant=TENANT,
        order_id=shipped.id,
        reason="尺码偏大退货",
        amount=100,
        trace_id="t-disp-1",
        applicant="tester",
    )
    wh = await _wh(db, "中心仓")
    sku_rows = [(i["sku_id"], int(i["qty"])) for i in json.loads(shipped.items or "[]")]
    assert sku_rows, "种子订单应含行快照"
    sku_id, qty = sku_rows[0]
    before = (await _inv(db, wh.id, sku_id)).qty

    result = await order_service.dispose(
        db,
        tenant=TENANT,
        aftersale_id=created["aftersale_id"],
        disposition="restocked",
        applicant="tester",
    )
    assert result["disposition"] == "restocked" and result["need_approval"] is False
    after = (await _inv(db, wh.id, sku_id)).qty
    assert after == before + qty
    detail = await order_service.get_detail(db, tenant=TENANT, order_id=shipped.id)
    nested = [a for a in detail["aftersales"] if a["id"] == created["aftersale_id"]]
    assert nested and nested[0]["disposition"] == "restocked"
    assert nested[0]["disposition_label"] == "二次入库"

    with pytest.raises(BusinessError) as again:
        await order_service.dispose(
            db,
            tenant=TENANT,
            aftersale_id=created["aftersale_id"],
            disposition="returned",
        )
    assert again.value.code == ErrorCode.ORDER_STATE_ILLEGAL


async def test_aftersale_dispose_scrap_approval(db: AsyncSession) -> None:
    """质检处置-报损：恒进审批，批准后 disposition=scrapped；无效处置类型 1001。"""
    shipped = await _order(db, "WX20260911003")
    created = await order_service.create_aftersale(
        db,
        tenant=TENANT,
        order_id=shipped.id,
        reason="面料破损",
        amount=100,
        trace_id="t-disp-2",
        applicant="tester",
    )
    with pytest.raises(BusinessError) as bad:
        await order_service.dispose(
            db, tenant=TENANT, aftersale_id=created["aftersale_id"], disposition="illegal"
        )
    assert bad.value.code == ErrorCode.PARAM_INVALID

    result = await order_service.dispose(
        db,
        tenant=TENANT,
        aftersale_id=created["aftersale_id"],
        disposition="scrapped",
        applicant="tester",
    )
    assert result["need_approval"] is True and result["approval_id"]

    approval = await approval_service.get_or_raise(db, TENANT, result["approval_id"])
    assert approval.action == "aftersale.scrap"
    with pytest.raises(BusinessError) as again:
        await order_service.dispose(
            db, tenant=TENANT, aftersale_id=created["aftersale_id"], disposition="returned"
        )
    assert again.value.code == ErrorCode.ORDER_STATE_ILLEGAL

    await approval_service.decide(
        db, tenant=TENANT, approval_id=approval.id, approve=True, approver="boss"
    )
    detail = await order_service.get_detail(db, tenant=TENANT, order_id=shipped.id)
    nested = [a for a in detail["aftersales"] if a["id"] == created["aftersale_id"]]
    assert nested and nested[0]["disposition"] == "scrapped"
    assert nested[0]["status"] == "done"


async def test_aftersale_list_server_pagination(db: AsyncSession) -> None:
    """售后列表服务端分页（前端红线）：分页/处置筛选/总数口径。"""
    shipped = await _order(db, "WX20260911003")
    for i in range(3):
        await order_service.create_aftersale(
            db,
            tenant=TENANT,
            order_id=shipped.id,
            reason=f"分页测试 {i}",
            amount=100,
            trace_id=f"t-page-{i}",
            applicant="tester",
        )
    first = await order_service.list_aftersales(db, tenant=TENANT, page=1, size=2)
    assert first["total"] >= 3 and len(first["items"]) == 2
    assert first["page"] == 1 and first["size"] == 2
    second = await order_service.list_aftersales(db, tenant=TENANT, page=2, size=2)
    assert len(second["items"]) == 1
    assert {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]} == set()

    only_done = await order_service.list_aftersales(db, tenant=TENANT, status="pending", size=100)
    assert all(r["status"] == "pending" for r in only_done["items"])

    with pytest.raises(BusinessError) as bad_status:
        await order_service.list_aftersales(db, tenant=TENANT, status="bogus")
    assert bad_status.value.code == ErrorCode.PARAM_INVALID
