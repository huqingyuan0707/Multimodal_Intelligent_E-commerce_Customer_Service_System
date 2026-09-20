"""闭环演示·业务记录种子（售后单/营销券/会员/评价/工单/评测 run + 采购/财务/风控）

链路：app.db.seed.ensure_closed_loop_demo() → _seed_biz_records()（喂售后、营销、
     评价工单、Studio、大屏退货率）+ _seed_biz_ops()（喂 /purchase、/finance、/risk 三页）；
     时间口径复用 seed_closed_loop._rel()。
对齐数据模型与存储设计.md §6 迁移节。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Aftersale,
    CouponGrant,
    EvalRun,
    FinanceBill,
    Member,
    Product,
    Promo,
    PurchaseOrder,
    Review,
    RiskEvent,
    SalesOrder,
    Sku,
    Supplier,
    Ticket,
    Warehouse,
)
from app.db.seed_closed_loop import _rel


async def _seed_biz_records(db: AsyncSession, *, tenant: str, orders: list[SalesOrder]) -> None:
    """售后单/营销/会员/评价/工单/评测 run：喂售后、营销、评价工单、Studio、大屏退货率。"""
    if orders:
        specs = (
            ("尺码偏大退货", 15900, "pending", "pending"),
            ("袖口脱线换货", 12900, "approving", "pending"),
            ("面料勾丝退货", 29900, "done", "restocked"),
            ("物流破损退货", 12900, "done", "scrapped"),
        )
        for index, (reason, amount, status, disposition) in enumerate(specs):
            order = orders[index % len(orders)]
            db.add(
                Aftersale(
                    tenant=tenant,
                    sales_order_id=order.id,
                    reason=reason,
                    amount=amount,
                    evidence=json.dumps([], ensure_ascii=False),
                    trace_id=order.trace_id,
                    status=status,
                    disposition=disposition,
                    created_at=_rel(4.0 + index * 6),
                )
            )
    # status 不显式赋值：与 promo_service.create_promo 同口径（落模型默认 "draft"），
    # 避免种子里出现后端代码产不出的状态值（发布流 P2 未实现）
    promo = Promo(
        tenant=tenant,
        name="9 月秋冬上新｜满 300 减 50",
        budget=500,
        granted=0,
        total=0,
        per_user=1,
        created_at=_rel(72.0),
    )
    db.add(promo)
    await db.flush()
    for index, user_ref in enumerate(("buyer-1001", "buyer-1002", "buyer-1003")):
        db.add(
            CouponGrant(
                tenant=tenant,
                promo_id=promo.id,
                user_ref=user_ref,
                order_ref=f"BF{user_ref[-4:]}",
                status="granted",
                idem_key=f"seed-coupon-{user_ref}",
                created_at=_rel(6.0 + index),
            )
        )
    promo.granted = 3
    promo.total = 3
    # 等级口径同 promo_service._level_for（≥5000 v2 / ≥1000 v1 / 其余 v0），不编表外等级
    for user_ref, level, points in (
        ("buyer-1001", "v2", 5200),
        ("buyer-1002", "v1", 1860),
        ("buyer-1003", "v0", 120),
    ):
        db.add(Member(tenant=tenant, user_ref=user_ref, level=level, points=points))
    review = Review(
        tenant=tenant,
        platform="taobao",
        outer_id="BF202609001",
        level="bad",
        content="袖口有脱线，客服处理还算及时。",
        tags=json.dumps(["质量", "售后"], ensure_ascii=False),
        replied=False,
        created_at=_rel(20.0),
    )
    db.add(review)
    await db.flush()
    # 差评建单口径同 review_service.create_review_ticket：kind=review + SLA 2h + ticket_id 回写
    review_ticket = Ticket(
        tenant=tenant,
        kind="review",
        source_ref=review.id,
        assignee="liuwei",
        sla_due=_rel(-2.0),
        status="open",
        conclusion="",
        created_at=_rel(20.0),
    )
    db.add(review_ticket)
    await db.flush()
    review.ticket_id = review_ticket.id
    db.add(
        Ticket(
            tenant=tenant,
            kind="logistics",
            source_ref="BF202609002",
            assignee="chenyu",
            sla_due=_rel(2.0),
            status="closed",
            conclusion="承运商已恢复揽收，物流轨迹正常更新。",
            created_at=_rel(44.0),
        )
    )
    db.add(
        Review(
            tenant=tenant,
            platform="douyin",
            outer_id="BF202609003",
            level="good",
            content="发货很快，尺码也准。",
            tags=json.dumps(["物流", "尺码"], ensure_ascii=False),
            replied=True,
            reply="感谢支持，秋冬新品已上架，欢迎再来。",
            created_at=_rel(30.0),
        )
    )
    db.add(
        EvalRun(
            tenant=tenant,
            name="default-200",
            limit=200,
            status="done",
            score=json.dumps(
                {
                    "total": 200,
                    "answerable": 160,
                    "refuse": 40,
                    "grounded": 0.96,
                    "hallucination": 0.02,
                    "per_scene": {
                        "售后": {"total": 60, "hit": 58},
                        "尺码": {"total": 100, "hit": 96},
                    },
                    "guard_dist": {"injection": 4, "off_domain": 2},
                    "misses": [],
                    "ratchet_ok": True,
                    "accept_ok": True,
                },
                ensure_ascii=False,
            ),
            elapsed_ms=12000,
            created_by=settings.SEED_USERNAME,
            created_at=_rel(36.0),
        )
    )
    await db.flush()


async def _seed_biz_ops(db: AsyncSession, *, tenant: str, skus: list[Sku]) -> None:
    """采购/财务/风控三页种子：供应商 + 采购单（状态机四档）+ 日结单 + 风控事件。

    采购单只铺 draft/approved/received/returned（**不伪造 stocked**）：「已入库」必须由
    真实质检流程写 inventory + stock_moves 才成立，种子造空壳会污染库存口径；
    留一张已到货单，让「质检→入库」这条链路可由页面当场走通。
    """
    if not skus:
        return
    houses = list((await db.execute(select(Warehouse).where(Warehouse.tenant == tenant))).scalars())
    house = houses[0].id if houses else ""
    names = {
        str(pid): (str(name), str(spu))
        for pid, name, spu in (
            await db.execute(
                select(Product.id, Product.name, Product.spu_no).where(Product.tenant == tenant)
            )
        ).all()
    }
    suppliers = [
        Supplier(
            tenant=tenant,
            name="杭州锦棉纺织",
            pay_terms="月结 30 天",
            pass_rate=0.98,
            created_at=_rel(240.0),
        ),
        Supplier(
            tenant=tenant,
            name="苏州云锦制衣",
            pay_terms="半月结",
            pass_rate=0.94,
            created_at=_rel(200.0),
        ),
        Supplier(
            tenant=tenant,
            name="东莞恒丰辅料",
            pay_terms="现结",
            pass_rate=0.885,
            created_at=_rel(160.0),
        ),
    ]
    for row in suppliers:
        db.add(row)
    await db.flush()

    def _line(index: int, qty: int, price: int) -> dict:
        sku = skus[index % len(skus)]
        product = names.get(sku.product_id, ("", ""))
        return {
            "sku_id": sku.id,
            "name": product[0],
            "spu_no": product[1],
            "color": sku.color,
            "size": sku.size,
            "qty": qty,
            "price": price,
        }

    today = datetime.now()
    # (供应商序号, 状态, 明细, 到货日偏移天, 质检结论, 质检说明, 创建时间回推小时)
    for sup, status, lines, eta_days, qc, note, hours in (
        (0, "draft", [_line(0, 200, 8900)], 7, "", "", 6.0),
        (1, "approved", [_line(1, 120, 12900)], 10, "", "", 30.0),
        (0, "received", [_line(2, 80, 29900)], 2, "", "", 54.0),
        (1, "returned", [_line(3, 60, 9900)], -2, "fail", "到货色差超标，整批退供", 78.0),
    ):
        db.add(
            PurchaseOrder(
                tenant=tenant,
                supplier_id=suppliers[sup].id,
                warehouse_id=house if status in ("received", "stocked") else "",
                items=json.dumps(lines, ensure_ascii=False),
                status=status,
                eta=(today + timedelta(days=eta_days)).strftime("%Y-%m-%d"),
                qc_result=qc,
                qc_note=note,
                created_at=_rel(hours),
            )
        )
    # (距今天数, 应收, 退款, 扣点, 运费, 实收偏差)：偏差 0 即对平，负数=少收（绝对值超阈值亮红）
    for days, receivable, refund, fee, freight, delta in (
        (0, 1286000, 32000, 25700, 0, 0),
        (1, 1146000, 18000, 22900, 0, -12000),
        (2, 980000, 26000, 19600, 0, 600),
        (3, 1342000, 41000, 26800, 1200, -800),
        (4, 906000, 12000, 18100, 0, 0),
    ):
        day = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        expected = receivable - refund - fee + freight
        db.add(
            FinanceBill(
                tenant=tenant,
                biz_date=day,
                receivable=receivable,
                received=expected + delta,
                refund=refund,
                fee=fee,
                freight=freight,
                diff=delta,
                # 最新账期待日结（保证 /finance 首屏有可确认单），历史账期视为已复核结清
                # （双人复核两步：settled_by=制单人 admin，reviewed_by=换人复核演示账号）
                settled_by="" if days == 0 else settings.SEED_USERNAME,
                reviewed_by="" if days == 0 else "liuwei",
                created_at=_rel(days * 24 + 1),
            )
        )
    for user_ref, kind, status, detail, reviewer, reason, hours in (
        (
            "buyer-2088",
            "refund_abuse",
            "pending",
            '{"device":"D-88f1","payment":"PA-7732","refund_30d":7,"linked_accounts":3}',
            "",
            "",
            3.0,
        ),
        (
            "buyer-1902",
            "order_risk",
            "pending",
            '{"device":"D-21a9","payment":"PA-1180","refund_30d":4,"linked_accounts":2}',
            "",
            "",
            9.0,
        ),
        (
            "buyer-1003",
            "coupon_abuse",
            "passed",
            '{"device":"D-77c2","payment":"PA-9021","refund_30d":0,"linked_accounts":0}',
            settings.SEED_USERNAME,
            "新客首单，非团伙特征",
            26.0,
        ),
        (
            "buyer-2077",
            "account_link",
            "blocked",
            '{"device":"D-88f1","payment":"PA-7732","refund_30d":9,"linked_accounts":5}',
            "liuwei",
            "与 3 个退款高风险账号共用设备与支付账号",
            50.0,
        ),
    ):
        db.add(
            RiskEvent(
                tenant=tenant,
                user_ref=user_ref,
                kind=kind,
                detail=detail,
                status=status,
                reviewer=reviewer,
                reason=reason,
                created_at=_rel(hours),
            )
        )
    await db.flush()
