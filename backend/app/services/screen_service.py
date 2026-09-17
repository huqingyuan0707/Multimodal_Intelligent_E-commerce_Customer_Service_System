"""经营大屏汇总（真实聚合，对齐 API 规范 §4.6 大屏节 + 页面设计 §3.15）

链路：GET /screen/summary → 本模块 → sales_orders/sessions/aftersales/inventory 聚合。
口径（无运行时数据的指标一律回 '—' 不编数，与 dashboard_service 同款红线）：
- GMV：sales_orders.total 按日分桶（今日/昨日涨跌 + 近 7 日趋势，只看已付款订单）
- 自动解决率：handoff_status=='none' 会话占比；幻觉率无运行时采集 → '—'
- 退货率：售后单件数 / 已付款订单件数；Top 原因按 reason 聚合
- 缺货/预警：inventory 可用量（qty-reserved-locked）≤0 或缺低于 warn_line 的 SKU 数
- 预警列表：库存低于安全线 / 退货 Top 原因（level: bad|info）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.user_context import CurrentUser
from app.db.models import Aftersale, Inventory, Product, SalesOrder, Session, Sku, Warehouse
from app.services import goods_service

_GMV_STATUSES = ("paid", "shipped", "completed")
_TREND_DAYS = 7
_WARN_LIST_LIMIT = 5  # 大屏预警列表最多展示条数，避免刷屏


async def _tenant_list(db: AsyncSession, user: CurrentUser) -> list[str]:
    """可见租户：admin 看全租户（sessions 去重），否则只看本租户（同 dashboard_service）。"""
    if "admin" in user.roles or "*" in user.roles:
        rows = (await db.execute(select(Session.tenant).distinct().order_by(Session.tenant))).all()
        tenants = [str(r[0]) for r in rows if r[0]]
        return tenants or [user.tenant]
    return [user.tenant]


async def _gmv_trend(
    db: AsyncSession, *, tenants: list[str], now: datetime
) -> tuple[list[dict[str, Any]], int, int]:
    """近 7 日 GMV 趋势 + 今日/昨日值（分）。"""
    days = [(now - timedelta(days=i)).date() for i in range(_TREND_DAYS - 1, -1, -1)]
    trend: list[dict[str, Any]] = []
    today_cents = 0
    yesterday_cents = 0
    for day in days:
        start = datetime(day.year, day.month, day.day)
        cents = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(SalesOrder.total), 0)).where(
                        SalesOrder.tenant.in_(tenants),
                        SalesOrder.status.in_(_GMV_STATUSES),
                        SalesOrder.created_at >= start,
                        SalesOrder.created_at < start + timedelta(days=1),
                    )
                )
            ).scalar_one()
        )
        if day == days[-1]:
            today_cents = cents
        if day == days[-2]:
            yesterday_cents = cents
        trend.append({"label": day.strftime("%m-%d"), "value": cents})
    return trend, today_cents, yesterday_cents


async def _solve_and_return(db: AsyncSession, *, tenants: list[str]) -> tuple[str, str, str, float]:
    """自动解决率（%）与退货率（%）与 Top 退货原因与退货率真实比值（0..1）。"""
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Session).where(Session.tenant.in_(tenants))
            )
        ).scalar_one()
    )
    auto = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Session)
                .where(Session.tenant.in_(tenants), Session.handoff_status == "none")
            )
        ).scalar_one()
    )
    solve = f"{auto / total * 100:.0f}%" if total else "—"

    orders = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SalesOrder)
                .where(SalesOrder.tenant.in_(tenants), SalesOrder.status.in_(_GMV_STATUSES))
            )
        ).scalar_one()
    )
    aftersales = int(
        (
            await db.execute(
                select(func.count()).select_from(Aftersale).where(Aftersale.tenant.in_(tenants))
            )
        ).scalar_one()
    )
    return_rate = f"{aftersales / orders * 100:.1f}%" if orders else "—"
    ratio = aftersales / orders if orders else 0.0

    top = (
        await db.execute(
            select(Aftersale.reason, func.count())
            .where(Aftersale.tenant.in_(tenants), Aftersale.reason != "")
            .group_by(Aftersale.reason)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()
    return solve, return_rate, (top[0] if top else ""), ratio


async def _stock_warns(db: AsyncSession, *, tenants: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """缺货/预警 SKU 数 + 库存预警列表（低于安全线，缺货优先 bad）。"""
    rows = (
        await db.execute(
            select(Inventory, Sku, Warehouse, Product)
            .join(Sku, Inventory.sku_id == Sku.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .join(Product, Sku.product_id == Product.id)
            .where(Inventory.tenant.in_(tenants))
        )
    ).all()
    out_of_stock = 0
    below_warn = 0
    warns: list[dict[str, Any]] = []
    for inv, sku, wh, product in rows:
        available = inv.qty - inv.reserved - inv.locked
        code = goods_service.sku_code(product.spu_no, sku.color, sku.size)
        if available <= 0:
            out_of_stock += 1
            warns.append(
                {
                    "id": inv.id,
                    "content": f"{code}（{wh.name}）已缺货，待补货",
                    "level": "bad",
                }
            )
        elif available < inv.warn_line:
            below_warn += 1
            warns.append(
                {
                    "id": inv.id,
                    "content": f"{code}（{wh.name}）可用 {available} 低于安全线 {inv.warn_line}",
                    "level": "info",
                }
            )
    warns = warns[:_WARN_LIST_LIMIT]
    return f"{out_of_stock} / {out_of_stock + below_warn}", warns


async def summary(db: AsyncSession, *, user: CurrentUser) -> dict[str, Any]:
    """大屏汇总：4 指标 + 近 7 日 GMV 趋势 + 预警列表（无据一律 '—'，不编数）。"""
    now = datetime.now()
    tenants = await _tenant_list(db, user)
    trend, today_cents, yesterday_cents = await _gmv_trend(db, tenants=tenants, now=now)
    solve, return_rate, top_reason, return_ratio = await _solve_and_return(db, tenants=tenants)
    stock_text, warnings = await _stock_warns(db, tenants=tenants)

    # 退货突增（占比超 Settings 阈值）排在最前：大屏预警优先级最高的业务异常
    if return_ratio > settings.SCREEN_RETURN_WARN_RATIO:
        warnings.insert(
            0,
            {
                "id": "return-spike",
                "content": (
                    f"退货率 {return_rate} 超阈值 "
                    f"{settings.SCREEN_RETURN_WARN_RATIO * 100:.0f}%"
                    f"（Top 原因：{top_reason or '未归类'}）→ 会话/质检下钻 → 补知识待回归"
                ),
                "level": "bad",
            },
        )
    warnings = warnings[:_WARN_LIST_LIMIT]

    gmv_yuan = f"￥{today_cents / 100:,.0f}"
    if yesterday_cents:
        growth = (today_cents - yesterday_cents) / yesterday_cents * 100
        gmv_value = f"{gmv_yuan} ↑{growth:.0f}%" if growth >= 0 else f"{gmv_yuan} ↓{-growth:.0f}%"
    else:
        gmv_value = f"{gmv_yuan} ↑—"
    solve_value = f"{solve} / —"  # 幻觉率无运行时采集，不编数

    metrics = [
        {"key": "gmv", "label": "GMV（今日/昨日）", "value": gmv_value, "tone": "up"},
        {"key": "solve", "label": "自动解决率 / 幻觉率", "value": solve_value, "tone": "good"},
        {
            "key": "return",
            "label": f"退货率 · Top原因{top_reason or '—'}",
            "value": return_rate,
            "tone": "bad",
        },
        {"key": "stock", "label": "缺货SKU / 安全预警", "value": stock_text, "tone": "warn"},
    ]

    return {"metrics": metrics, "trend": trend, "warnings": warnings}
