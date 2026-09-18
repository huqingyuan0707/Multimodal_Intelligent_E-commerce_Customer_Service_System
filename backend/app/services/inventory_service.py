"""库存服务（/inventory：可用量唯一口径 + 出入库 / 调拨；预占与盘点已分家）

链路：endpoints/inventory → 本模块 → inventory/stock_moves 表。
分家：预占/释放/确认 → reserve_service；盘点/差异生效/补货 → stocktake_service；
      本模块保留可用量口径、库存行读写与出入库（两者反向 import 本模块的共用件）。
红线：
- available = qty - reserved - locked，**全站唯一在此计算**（数据模型文档 §2.1），
  前端与各页禁止自算。
- 每行出入库必须带原因（缺原因 1001）；调拨拆「出 A 仓 + 入 B 仓」两行流水。
- 库存数量/预占变更后必须 sync_gate 回写预占闸门，否则闸门停在旧值（数据模型 §4）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import cache
from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Inventory, Product, Sku, StockMove, Warehouse

# 出入库类型口径（唯一出处，前后端以此为准）：
# - 用户可提交：in 入库 / out 出库 / move 调拨（move 必带 to_warehouse_id，自动拆两行流水）。
# - adjust 调整：系统内部专用（盘点差异审批通过后 apply_stocktake 写入），不接受用户直接提交。
MOVE_KINDS = ("in", "out", "move")
KIND_LABELS = {"in": "入库", "out": "出库", "move": "调拨", "adjust": "调整"}


def available_of(row: Inventory) -> int:
    """可用量唯一口径（改这里等于改全站，其他模块只读不重算）。"""
    return row.qty - row.reserved - row.locked


def stock_key(tenant: str, warehouse_id: str, sku_id: str) -> str:
    """库存预占闸门键（数据模型 §4：stock:{tenant}:{warehouse}:{sku}）。"""
    return f"stock:{tenant}:{warehouse_id}:{sku_id}"


async def sync_gate(row: Inventory) -> None:
    """把预占闸门对齐到 DB 真值（库存数量变更后唯一回写口，防闸门停在旧值）。

    闸门只在首次预占时以 base_available 初始化，此后出入库/调拨/盘点都必须经此回写，
    否则预占按过期可用量判定。DB 始终是事实源，闸门只是原子闸门。
    """
    await cache.stock_sync(
        stock_key(row.tenant, row.warehouse_id, row.sku_id), row.qty, row.reserved, row.locked
    )


async def get_row(
    db: AsyncSession,
    tenant: str,
    warehouse_id: str,
    sku_id: str,
    *,
    create_if_missing: bool = False,
) -> Inventory | None:
    """取库存行；create_if_missing 用于入库/调拨落到尚无记录的仓库。"""
    row = (
        await db.execute(
            select(Inventory).where(
                Inventory.tenant == tenant,
                Inventory.warehouse_id == warehouse_id,
                Inventory.sku_id == sku_id,
            )
        )
    ).scalar_one_or_none()
    if row is None and create_if_missing:
        row = Inventory(
            tenant=tenant,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            qty=0,
            warn_line=settings.STOCK_WARN_DEFAULT,
        )
        db.add(row)
        await db.flush()
    return row


async def sku_or_raise(db: AsyncSession, tenant: str, sku_id: str) -> tuple[Sku, Product]:
    sku = (
        await db.execute(select(Sku).where(Sku.tenant == tenant, Sku.id == sku_id))
    ).scalar_one_or_none()
    if sku is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "SKU 不存在或无权访问", 404)
    product = (
        await db.execute(
            select(Product).where(Product.tenant == tenant, Product.id == sku.product_id)
        )
    ).scalar_one_or_none()
    if product is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "SKU 所属商品不存在", 404)
    return sku, product


async def warehouse_or_raise(db: AsyncSession, tenant: str, warehouse_id: str) -> Warehouse:
    row = (
        await db.execute(
            select(Warehouse).where(Warehouse.tenant == tenant, Warehouse.id == warehouse_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "仓库不存在或无权访问", 404)
    return row


async def stock_table(
    db: AsyncSession,
    *,
    tenant: str,
    warehouse_id: str = "",
    sku_id: str = "",
    keyword: str = "",
    only_warn: bool = False,
    page: int = 1,
    size: int = 50,
) -> dict[str, Any]:
    """库存表（SKU × 仓库）：一次算好 available / warning 再返回。

    行数受「SKU × 仓库」约束，P1 在内存里过滤安全线并分页；
    迁 PG 后把 available 下推为计算列（数据模型文档 §6 迁移注意）。
    keyword 搜 SKU 编码 / SPU / 品名 / 颜色 / 尺码 / 仓库名，过滤发生在服务端分页之前。
    """
    stmt = (
        select(Inventory, Warehouse, Sku, Product)
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .join(Sku, Sku.id == Inventory.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .where(Inventory.tenant == tenant)
    )
    if warehouse_id:
        stmt = stmt.where(Inventory.warehouse_id == warehouse_id)
    if sku_id:
        stmt = stmt.where(Inventory.sku_id == sku_id)
    rows = list((await db.execute(stmt.order_by(Product.spu_no, Warehouse.name))).all())

    items: list[dict[str, Any]] = []
    for inv, warehouse, sku, product in rows:
        avail = available_of(inv)
        warning = avail < inv.warn_line
        if only_warn and not warning:
            continue
        item = {
            "id": inv.id,
            "warehouse_id": warehouse.id,
            "warehouse": warehouse.name,
            "sku_id": sku.id,
            "spu_no": product.spu_no,
            "product_name": product.name,
            "color": sku.color,
            "size": sku.size,
            "sku_code": "-".join(p for p in (product.spu_no, sku.color, sku.size) if p),
            "qty": inv.qty,
            "reserved": inv.reserved,
            "locked": inv.locked,
            "available": avail,
            "warn_line": inv.warn_line,
            "warning": warning,
        }
        if keyword:
            kw = keyword.strip().lower()
            haystack = " ".join(
                str(v).lower()
                for v in (
                    item["sku_code"],
                    item["spu_no"],
                    item["product_name"],
                    item["color"],
                    item["size"],
                    item["warehouse"],
                )
            )
            if kw and kw not in haystack:
                continue
        items.append(item)
    total = len(items)
    start = (page - 1) * size
    return {"total": total, "page": page, "size": size, "items": items[start : start + size]}


async def list_warehouses(db: AsyncSession, *, tenant: str) -> list[Warehouse]:
    rows = (
        await db.execute(
            select(Warehouse).where(Warehouse.tenant == tenant).order_by(Warehouse.name)
        )
    ).scalars()
    return list(rows)


async def list_moves(
    db: AsyncSession, *, tenant: str, sku_id: str = "", limit: int = 50
) -> list[StockMove]:
    stmt = select(StockMove).where(StockMove.tenant == tenant)
    if sku_id:
        stmt = stmt.where(StockMove.sku_id == sku_id)
    rows = (await db.execute(stmt.order_by(StockMove.created_at.desc()).limit(limit))).scalars()
    return list(rows)


def check_delta(delta: int) -> None:
    if delta <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "数量必须是正整数")


def check_reason(reason: str) -> str:
    """出入库原因必填（报损/退货/盘盈盘亏都要留痕）。"""
    text = reason.strip()
    if not text:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请填写出入库原因（报损、退货等必须留痕）")
    return text


async def move_stock(
    db: AsyncSession,
    *,
    tenant: str,
    kind: str,
    warehouse_id: str,
    sku_id: str,
    delta: int,
    reason: str,
    actor: str,
    to_warehouse_id: str = "",
    order_ref: str = "",
) -> dict[str, Any]:
    """入库 / 出库 / 调拨。

    - in：qty += delta
    - out：可用量不足直接 3004（不产生流水）
    - move：拆「出源仓 + 入目标仓」两行流水（数据模型文档 §2.1 stock_moves 口径）
    """
    if kind not in MOVE_KINDS:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"出入库类型非法：{kind}（可选 {'/'.join(MOVE_KINDS)}）"
        )
    check_delta(delta)
    text = check_reason(reason)
    await sku_or_raise(db, tenant, sku_id)
    source = await warehouse_or_raise(db, tenant, warehouse_id)

    if kind == "in":
        row = await get_row(db, tenant, warehouse_id, sku_id, create_if_missing=True)
        assert row is not None  # create_if_missing 保证非空
        row.qty += delta
        db.add(
            StockMove(
                tenant=tenant,
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                kind="in",
                delta=delta,
                reason=text,
                order_ref=order_ref,
                actor=actor,
            )
        )
    elif kind == "out":
        row = await get_row(db, tenant, warehouse_id, sku_id)
        if row is None:
            raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录", 404)
        avail = available_of(row)
        if avail < delta:
            raise BusinessError(
                ErrorCode.STOCK_SHORTAGE,
                f"可用库存不足：{source.name} 当前可用 {avail}，本次需出库 {delta}",
            )
        row.qty -= delta
        db.add(
            StockMove(
                tenant=tenant,
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                kind="out",
                delta=-delta,
                reason=text,
                order_ref=order_ref,
                actor=actor,
            )
        )
    else:  # move
        if not to_warehouse_id or to_warehouse_id == warehouse_id:
            raise BusinessError(ErrorCode.PARAM_INVALID, "调拨需要选择与原仓库不同的目标仓库")
        target = await warehouse_or_raise(db, tenant, to_warehouse_id)
        row = await get_row(db, tenant, warehouse_id, sku_id)
        if row is None:
            raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录", 404)
        avail = available_of(row)
        if avail < delta:
            raise BusinessError(
                ErrorCode.STOCK_SHORTAGE,
                f"可用库存不足：{source.name} 当前可用 {avail}，本次需调拨 {delta}",
            )
        row.qty -= delta
        db.add(
            StockMove(
                tenant=tenant,
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                kind="move",
                delta=-delta,
                reason=f"调拨至 {target.name}：{text}",
                order_ref=order_ref,
                actor=actor,
            )
        )
        inbound = await get_row(db, tenant, to_warehouse_id, sku_id, create_if_missing=True)
        assert inbound is not None
        inbound.qty += delta
        db.add(
            StockMove(
                tenant=tenant,
                warehouse_id=to_warehouse_id,
                sku_id=sku_id,
                kind="move",
                delta=delta,
                reason=f"自 {source.name} 调入：{text}",
                order_ref=order_ref,
                actor=actor,
            )
        )

    await db.commit()
    final = await get_row(db, tenant, warehouse_id, sku_id)
    if final is not None:
        await sync_gate(final)
    if kind == "move":
        target_final = await get_row(db, tenant, to_warehouse_id, sku_id)
        if target_final is not None:
            await sync_gate(target_final)
    return {
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "warehouse": source.name,
        "qty": final.qty if final else 0,
        "available": available_of(final) if final else 0,
    }
