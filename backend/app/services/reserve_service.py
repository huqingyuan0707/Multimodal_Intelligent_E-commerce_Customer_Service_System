"""库存预占服务（/inventory/reserve：下单锁可用量，随订单生命周期收口）

链路：endpoints/inventory 的 reserve/release/confirm → 本模块 → core/cache 预占闸门
      + inventory 表（reserved/qty 双写）+ stock_moves（确认扣减留痕）。
对齐：数据模型与存储设计.md §4 `stock:{tenant}:{warehouse}:{sku}`（原子扣减，DB 双写）、API 规范 §4.7。
两道防线（并发零超卖）：
- 第一道 core/cache.stock_reserve：Redis Lua 原子扣减，不足即 3004；Redis 不可用降级进程内锁。
- 第二道 DB 行锁（with_for_update，PG 生效）：同事务复校验并落 reserved；DB 失败回补闸门。
预占随订单生命周期由 release（取消/超时）与 confirm（支付/发货）收口。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Inventory, StockMove
from app.services.inventory_service import (
    available_of,
    check_delta,
    get_row,
    stock_key,
    warehouse_or_raise,
)


async def reserve_capacity(
    db: AsyncSession,
    *,
    tenant: str,
    warehouse_id: str,
    sku_id: str,
    qty: int,
    order_ref: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """预占库存：Redis 原子闸门 + DB 双写 reserved（数据模型 §4 stock:{tenant}:{warehouse}:{sku}）。

    - 第一道防线：cache.stock_reserve（Redis Lua，单进程降级为内存锁）原子扣减，不足即 3004；
    - 第二道防线：DB 行锁（with_for_update，PG 生效；SQLite 单写者）同事务校验并落 reserved；
    - DB 失败回补闸门，保证闸门与 DB 不漂移。预占随订单生命周期由 release/confirm 收口。
    """
    check_delta(qty)
    source = await warehouse_or_raise(db, tenant, warehouse_id)
    row = await get_row(db, tenant, warehouse_id, sku_id)
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录，无法预占", 404)
    key = stock_key(tenant, warehouse_id, sku_id)
    if not await cache.stock_reserve(key, qty, base_available=available_of(row)):
        raise BusinessError(
            ErrorCode.STOCK_SHORTAGE,
            f"可用库存不足：{source.name} 当前可用 {available_of(row)}，本次需预占 {qty}",
        )
    try:
        locked = (
            await db.execute(
                select(Inventory)
                .where(
                    Inventory.tenant == tenant,
                    Inventory.warehouse_id == warehouse_id,
                    Inventory.sku_id == sku_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked is None:
            raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录，无法预占", 404)
        if available_of(locked) < qty:
            raise BusinessError(
                ErrorCode.STOCK_SHORTAGE,
                f"可用库存不足：{source.name} 当前可用 {available_of(locked)}，本次需预占 {qty}",
            )
        locked.reserved += qty
        await db.commit()
    except Exception:
        await cache.stock_release(key, qty)  # 回补闸门（尽力而为，防漂移；失败残留只误拒不超发）
        raise
    return {
        "warehouse_id": warehouse_id,
        "sku_id": sku_id,
        "qty": qty,
        "reserved": locked.reserved,
        "available": available_of(locked),
        "order_ref": order_ref,
    }


async def release_reserve(
    db: AsyncSession,
    *,
    tenant: str,
    warehouse_id: str,
    sku_id: str,
    qty: int,
    order_ref: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """释放预占（订单取消/超时）：DB 先回吐 reserved，再同步 Redis 闸门；超量释放 3004。"""
    check_delta(qty)
    source = await warehouse_or_raise(db, tenant, warehouse_id)
    row = await get_row(db, tenant, warehouse_id, sku_id)
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录，无法释放", 404)
    if row.reserved < qty:
        raise BusinessError(
            ErrorCode.STOCK_SHORTAGE,
            f"释放量超过已预占量：{source.name} 已预占 {row.reserved}，本次释放 {qty}",
        )
    row.reserved -= qty
    await db.commit()
    await cache.stock_release(stock_key(tenant, warehouse_id, sku_id), qty)  # 同步闸门（尽力）
    return {
        "warehouse_id": warehouse_id,
        "sku_id": sku_id,
        "qty": qty,
        "reserved": row.reserved,
        "available": available_of(row),
        "order_ref": order_ref,
    }


async def confirm_reserve(
    db: AsyncSession,
    *,
    tenant: str,
    warehouse_id: str,
    sku_id: str,
    qty: int,
    order_ref: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """预占确认扣减（订单支付/发货）：qty/reserved 同扣 + 出库流水留痕，再同步 Redis 闸门。"""
    check_delta(qty)
    await warehouse_or_raise(db, tenant, warehouse_id)
    locked = (
        await db.execute(
            select(Inventory)
            .where(
                Inventory.tenant == tenant,
                Inventory.warehouse_id == warehouse_id,
                Inventory.sku_id == sku_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录，无法确认扣减", 404)
    if locked.qty < qty or locked.reserved < qty:
        raise BusinessError(
            ErrorCode.STOCK_SHORTAGE,
            f"可确认预占不足：账面 {locked.qty} / 已预占 {locked.reserved}，本次确认 {qty}",
        )
    locked.qty -= qty
    locked.reserved -= qty
    db.add(
        StockMove(
            tenant=tenant,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            kind="out",
            delta=-qty,
            reason=f"预占确认扣减（订单 {order_ref or '-'}）",
            order_ref=order_ref,
            actor=actor,
        )
    )
    await db.commit()
    await cache.stock_confirm(stock_key(tenant, warehouse_id, sku_id), qty)  # 同步闸门（尽力）
    return {
        "warehouse_id": warehouse_id,
        "sku_id": sku_id,
        "qty": qty,
        "qty_after": locked.qty,
        "reserved": locked.reserved,
        "available": available_of(locked),
        "order_ref": order_ref,
    }
