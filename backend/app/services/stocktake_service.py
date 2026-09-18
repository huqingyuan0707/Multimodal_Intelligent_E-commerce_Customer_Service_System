"""盘点与补货服务（/inventory 的盘点差异走审批、安全线一键补货）

链路：endpoints/inventory 的 stocktake/replenish → 本模块 → inventory/stock_moves 表
      + approval_service（差异单/补货单）；审批通过后 approval_service 回调 apply_stocktake。
对齐：数据模型与存储设计.md §2.1（stock_moves 口径）、API 规范 §4.7。
红线：
- 盘点账实不一致**不直接改账**，生成审批单，批准后生效。
- apply_stocktake 改完账面数必须回写预占闸门（inventory_service.sync_gate），
  否则闸门停在旧值，后续预占按过期可用量判定（数据模型 §4）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Approval, StockMove
from app.services import approval_service
from app.services.inventory_service import (
    check_delta,
    check_reason,
    get_row,
    sku_or_raise,
    sync_gate,
    warehouse_or_raise,
)


async def stocktake(
    db: AsyncSession,
    *,
    tenant: str,
    lines: list[dict[str, Any]],
    reason: str,
    actor: str,
) -> dict[str, Any]:
    """盘点：账实一致的直接记为已核对，有差异的行生成审批单（不自动改账）。"""
    if not lines:
        raise BusinessError(ErrorCode.PARAM_INVALID, "盘点明细不能为空")
    text = check_reason(reason)
    checked = 0
    approvals: list[Approval] = []
    for line in lines:
        warehouse_id = str(line.get("warehouse_id", ""))
        sku_id = str(line.get("sku_id", ""))
        counted = line.get("counted")
        if not warehouse_id or not sku_id or not isinstance(counted, int) or counted < 0:
            raise BusinessError(
                ErrorCode.PARAM_INVALID,
                "盘点明细非法：需要 warehouse_id、sku_id 与非负整数 counted",
            )
        row = await get_row(db, tenant, warehouse_id, sku_id)
        if row is None:
            raise BusinessError(ErrorCode.NOT_FOUND, "该仓库无此 SKU 库存记录，无法盘点", 404)
        checked += 1
        diff = counted - row.qty
        if diff == 0:
            continue
        sku, product = await sku_or_raise(db, tenant, sku_id)
        warehouse = await warehouse_or_raise(db, tenant, warehouse_id)
        approvals.append(
            await approval_service.create(
                db,
                tenant=tenant,
                action="inventory.stocktake_diff",
                target=f"{product.spu_no} {sku.color}/{sku.size}｜{warehouse.name}",
                args={
                    "warehouse_id": warehouse_id,
                    "sku_id": sku_id,
                    "qty_before": row.qty,
                    "counted": counted,
                },
                reason=f"盘点差异 {diff:+d}：{text}",
                applicant=actor,
            )
        )
    await db.commit()
    return {
        "checked": checked,
        "diff_count": len(approvals),
        "approval_ids": [a.id for a in approvals],
    }


async def apply_stocktake(
    db: AsyncSession, *, tenant: str, args: dict[str, Any], actor: str
) -> None:
    """盘点差异审批通过后的生效动作：账面数量改为实盘数，并回写预占闸门。"""
    warehouse_id = str(args.get("warehouse_id", ""))
    sku_id = str(args.get("sku_id", ""))
    counted = args.get("counted")
    if not warehouse_id or not sku_id or not isinstance(counted, int) or counted < 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "审批参数缺失：需要实盘数量")
    row = await get_row(db, tenant, warehouse_id, sku_id)
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "库存行已不存在，无法应用盘点结果", 404)
    diff = counted - row.qty
    row.qty = counted
    db.add(
        StockMove(
            tenant=tenant,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            kind="adjust",
            delta=diff,
            reason=f"盘点差异审批通过（操作人 {actor}）",
            actor=actor,
        )
    )
    await sync_gate(row)


async def replenish(
    db: AsyncSession,
    *,
    tenant: str,
    sku_id: str,
    qty: int,
    reason: str,
    applicant: str,
) -> Approval:
    """低于安全线一键生成补货需求：进审批，采购单落地在 /purchase。"""
    check_delta(qty)
    sku, product = await sku_or_raise(db, tenant, sku_id)
    text = reason.strip() or f"{product.spu_no} {sku.color}/{sku.size} 低于安全线补货"
    approval = await approval_service.create(
        db,
        tenant=tenant,
        action="inventory.replenish",
        target=f"{product.spu_no} {product.name}｜{sku.color}/{sku.size}",
        args={"sku_id": sku_id, "qty": qty},
        reason=text,
        applicant=applicant,
    )
    await db.commit()
    return approval
