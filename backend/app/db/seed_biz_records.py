"""闭环演示·业务记录种子（售后单/营销券/会员/评价/工单/评测 run）

链路：app.db.seed.ensure_closed_loop_demo() → _seed_biz_records()（喂售后、营销、
     评价工单、Studio、大屏退货率）；时间口径复用 seed_closed_loop._rel()。
对齐数据模型与存储设计.md §6 迁移节。
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Aftersale,
    CouponGrant,
    EvalRun,
    Member,
    Promo,
    Review,
    SalesOrder,
    Ticket,
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
