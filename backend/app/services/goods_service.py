"""商品服务（/goods：SPU-SKU 矩阵、上下架、改价恒进审批、库存销量聚合、知识同步）

链路：endpoints/goods → 本模块 → products/skus 表 + approval_service（改价落审批）
      + inventory（库存聚合 available）+ sales_orders（销量聚合）+ document_service（知识同步）
红线（数据模型文档 §2.1 approvals）：改价**不直接生效**，一律生成审批单，
      由 approval_service.decide 批准后才写 SKU 售价。
知识同步（FR-10.1）：商品变更后自动同步一篇商品知识文档到 kb_docs，
      确保 RAG 检索命中最新价格信息，避免客服答旧价。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Approval, Inventory, KbChunk, KbDoc, Product, SalesOrder, Sku
from app.services import approval_service, vector_store
from app.services.document_lifecycle import _snapshot_version
from app.services.document_parse import _write_chunks, sha256_of, split_chunks
from app.services.knowledge_service import bump_corpus

GOODS_STATUSES = ("draft", "on", "off", "archived")
GOODS_STATUS_LABELS = {"draft": "草稿", "on": "在售", "off": "已下架", "archived": "已归档"}
SKU_STATUS_LABELS = {"on": "在售", "off": "停售"}

_SALES_STATUSES = ("paid", "shipped", "completed")

_logger = logging.getLogger(__name__)


def _parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return fallback


def sku_code(product_spu_no: str, color: str, size: str) -> str:
    """展示用 SKU 编码：SPU-颜色-尺码（口径全站唯一，前端不再自拼）。"""
    return "-".join(part for part in (product_spu_no, color, size) if part)


def sku_to_dict(sku: Sku, product_spu_no: str, available: int = 0) -> dict[str, Any]:
    return {
        "id": sku.id,
        "sku_code": sku_code(product_spu_no, sku.color, sku.size),
        "color": sku.color,
        "size": sku.size,
        "barcode": sku.barcode,
        "list_price": sku.list_price,
        "sale_price": sku.sale_price,
        "available": available,
        "status": sku.status,
        "status_label": SKU_STATUS_LABELS.get(sku.status, sku.status),
    }


def to_dict(
    product: Product,
    skus: list[Sku],
    available_by_sku: dict[str, int] | None = None,
    sales: int = 0,
) -> dict[str, Any]:
    available_by_sku = available_by_sku or {}
    return {
        "id": product.id,
        "spu_no": product.spu_no,
        "name": product.name,
        "category": product.category,
        "status": product.status,
        "status_label": GOODS_STATUS_LABELS.get(product.status, product.status),
        "images": _parse_json(product.images, []),
        "attrs": _parse_json(product.attrs, {}),
        "sales": sales,
        "created_at": product.created_at.isoformat(sep=" ", timespec="seconds"),
        "skus": [sku_to_dict(s, product.spu_no, available_by_sku.get(s.id, 0)) for s in skus],
    }


async def _get_product(db: AsyncSession, tenant: str, product_id: str) -> Product:
    row = (
        await db.execute(select(Product).where(Product.tenant == tenant, Product.id == product_id))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "商品不存在或无权访问", 404)
    return row


async def _get_sku(db: AsyncSession, tenant: str, sku_id: str) -> tuple[Sku, Product]:
    sku = (
        await db.execute(select(Sku).where(Sku.tenant == tenant, Sku.id == sku_id))
    ).scalar_one_or_none()
    if sku is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "SKU 不存在或无权访问", 404)
    product = await _get_product(db, tenant, sku.product_id)
    return sku, product


async def _sum_available_by_sku(
    db: AsyncSession, tenant: str, sku_ids: list[str]
) -> dict[str, int]:
    """聚合每 SKU 全仓可售量：available = SUM(qty - reserved - locked)。

    口径与 inventory_service.available_of 完全一致（改那里等于改全站），
    这里只是把同一公式批量化了，避免 N+1 查询。
    """
    if not sku_ids:
        return {}
    rows = list(
        (
            await db.execute(
                select(
                    Inventory.sku_id,
                    func.sum(Inventory.qty - Inventory.reserved - Inventory.locked).label("avail"),
                )
                .where(Inventory.tenant == tenant, Inventory.sku_id.in_(sku_ids))
                .group_by(Inventory.sku_id)
            )
        ).all()
    )
    return {row.sku_id: int(row.avail or 0) for row in rows}


async def _sum_sales_by_spu(
    db: AsyncSession, tenant: str, product_id_to_skus: dict[str, list[Sku]]
) -> dict[str | None, int]:
    """从已成交订单（paid/shipped/completed）聚合 SPU 级销量。

    订单行 items 为 JSON（含 sku_id/qty），Python 层按 sku_id 归并到 SPU；
    B 端订单量级有限，P1 内存聚合可接受（P2 迁 PG 后可下推 SQL）。
    """
    if not product_id_to_skus:
        return {}
    sku_to_spu = {sku.id: pid for pid, skus in product_id_to_skus.items() for sku in skus}
    rows = list(
        (
            await db.execute(
                select(SalesOrder.items).where(
                    SalesOrder.tenant == tenant,
                    SalesOrder.status.in_(_SALES_STATUSES),
                )
            )
        ).scalars()
    )
    sales: dict[str | None, int] = {}
    for raw in rows:
        for item in _parse_json(raw, []):
            sku_id = str(item.get("sku_id", ""))
            qty = item.get("qty", 0)
            if sku_id in sku_to_spu and isinstance(qty, int):
                sales[sku_to_spu[sku_id]] = sales.get(sku_to_spu[sku_id], 0) + qty
    return sales


def _kb_content(product: Product, skus: list[Sku], available_by_sku: dict[str, int]) -> str:
    """商品知识正文（面料/尺码/价格段三大客服高频问点，`##` 分节对齐切分器）。"""
    attrs = _parse_json(product.attrs, {})
    fabric = str(attrs.get("材质") or attrs.get("面料") or "见商品详情页")
    wash = str(attrs.get("洗涤方式") or "—")
    sizes = list(dict.fromkeys(sku.size for sku in skus))
    prices = [sku.sale_price for sku in skus]
    low, high = (min(prices), max(prices)) if prices else (0, 0)
    label = GOODS_STATUS_LABELS.get(product.status, product.status)
    lines = [
        f"# 商品知识｜{product.spu_no} {product.name}",
        f"（商品管理变更自动同步，供客服问答使用；类目：{product.category}；状态：{label}）",
        "",
        f"## 面料成分\n{fabric}\n洗涤方式：{wash}",
        f"## 尺码范围\n{' / '.join(sizes) if sizes else '—'}",
        f"## 价格段\n售价 ¥{low / 100:.2f} ~ ¥{high / 100:.2f}（当前）",
    ]
    if skus:
        lines.append("## SKU 明细")
        for s in skus:
            avail = available_by_sku.get(s.id, 0)
            status_label = SKU_STATUS_LABELS.get(s.status, s.status)
            lines.append(
                f"- {s.color}/{s.size}（{sku_code(product.spu_no, s.color, s.size)}）"
                f"售价 ¥{s.sale_price / 100:.2f}，条码 {s.barcode or '—'}，"
                f"可售 {avail} 件，{status_label}"
            )
    lines.append(f"\n同步时间：{datetime.now():%Y-%m-%d %H:%M}")
    return "\n".join(lines) + "\n"


async def sync_product_knowledge(
    db: AsyncSession,
    *,
    tenant: str,
    product: Product,
    skus: list[Sku],
    available_by_sku: dict[str, int] | None = None,
    actor: str = "",
) -> dict[str, Any]:
    """商品变更同步客服知识（FR-10.1）：upsert《商品知识｜SPU 名称》到 kb_docs。

    口径：**按标题幂等**（同一 SPU 永远一篇，价格变了改同一篇而非新开一篇），
    内容变才重切块并 version +1；本函数**不 commit**——与触发它的商品变更
    共用一个事务，要么同成要么同滚，避免"价格改了、知识还是旧价"。
    """
    title = f"商品知识｜{product.spu_no} {product.name}"
    content = _kb_content(product, skus, available_by_sku or {})
    digest = sha256_of(content.encode("utf-8"))
    row = (
        await db.execute(select(KbDoc).where(KbDoc.tenant == tenant, KbDoc.title == title))
    ).scalar_one_or_none()
    if row is None:
        row = KbDoc(
            tenant=tenant,
            title=title,
            content=content,
            topic="商品知识",
            status="published",
            sha256=digest,
            version=1,
            security_level="internal",
            channels=json.dumps(["all"], ensure_ascii=False),
        )
        db.add(row)
        await db.flush()
        await _write_chunks(db, row.id, split_chunks(content), tenant=tenant)
        await _snapshot_version(db, row, actor=actor, action="create")
    elif digest != row.sha256:
        old_ids = list(
            (await db.execute(select(KbChunk).where(KbChunk.doc_id == row.id))).scalars()
        )
        await vector_store.delete_by_chunk(tenant, [c.id for c in old_ids])
        # SQLite 外键级联不可靠，显式删块防孤儿（与 document_service.update_doc 同口径）
        await db.execute(delete(KbChunk).where(KbChunk.doc_id == row.id))
        row.sha256 = digest
        row.version += 1
        row.content = content
        row.status = "published"
        await _write_chunks(db, row.id, split_chunks(content), tenant=tenant)
        await _snapshot_version(db, row, actor=actor, action="update")
    bump_corpus(tenant)
    return {"doc_id": row.id, "title": row.title, "version": row.version}


async def _sync_knowledge_by_product_id(
    db: AsyncSession, *, tenant: str, product_id: str, actor: str = ""
) -> dict[str, Any]:
    """按商品 ID 聚齐 SKU + 可售库存后同步知识（三处变更入口共用的薄封装）。"""
    product = await _get_product(db, tenant, product_id)
    skus = list(
        (
            await db.execute(
                select(Sku)
                .where(Sku.tenant == tenant, Sku.product_id == product_id)
                .order_by(Sku.color, Sku.size)
            )
        ).scalars()
    )
    available = await _sum_available_by_sku(db, tenant, [s.id for s in skus])
    return await sync_product_knowledge(
        db, tenant=tenant, product=product, skus=skus, available_by_sku=available, actor=actor
    )


async def list_goods(
    db: AsyncSession,
    *,
    tenant: str,
    keyword: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """SPU 分页 + 一次取回全部 SKU（避免 N+1），供 /goods 矩阵展开。"""
    if status and status not in GOODS_STATUSES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"商品状态非法：{status}（可选 {'/'.join(GOODS_STATUSES)}）",
        )
    stmt = select(Product).where(Product.tenant == tenant)
    if status:
        stmt = stmt.where(Product.status == status)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Product.name.like(like), Product.spu_no.like(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(Product.created_at.desc(), Product.spu_no)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    grouped: dict[str, list[Sku]] = {}
    if rows:
        sku_rows = (
            await db.execute(
                select(Sku)
                .where(Sku.product_id.in_([r.id for r in rows]))
                .order_by(Sku.color, Sku.size)
            )
        ).scalars()
        for sku in sku_rows:
            grouped.setdefault(sku.product_id, []).append(sku)
    all_skus = [sku for skus in grouped.values() for sku in skus]
    available_by_sku = await _sum_available_by_sku(db, tenant, [sku.id for sku in all_skus])
    sales_by_spu = await _sum_sales_by_spu(db, tenant, grouped)
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            to_dict(r, grouped.get(r.id, []), available_by_sku, sales_by_spu.get(r.id, 0))
            for r in rows
        ],
    }


async def submit_price_change(
    db: AsyncSession,
    *,
    tenant: str,
    sku_id: str,
    new_price: int,
    reason: str,
    applicant: str,
) -> Approval:
    """改价申请：只落审批单，SKU 价格保持原值（红线：改价恒进审批）。"""
    if new_price <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "新售价必须是大于 0 的整数（单位：分）")
    if not reason.strip():
        raise BusinessError(ErrorCode.PARAM_INVALID, "请填写改价原因（审批需要）")
    sku, product = await _get_sku(db, tenant, sku_id)
    approval = await approval_service.create(
        db,
        tenant=tenant,
        action="sku.price_change",
        target=sku.id,
        args={
            "sku_id": sku.id,
            "old_price": sku.sale_price,
            "new_price": new_price,
        },
        reason=reason.strip(),
        applicant=applicant,
    )
    approval.target = f"{product.spu_no} {product.name}｜{sku.color}/{sku.size}"
    await db.commit()
    return approval


async def apply_price_change(
    db: AsyncSession, *, tenant: str, args: dict[str, Any], actor: str
) -> None:
    """审批通过后的生效动作（由 approval_service._apply 调用，不单独暴露端点）。

    价格写入 + 同步商品知识（价格段变了，RAG 必须拿到新价）；
    不 commit，由审批流的统一提交收尾。
    """
    sku_id = str(args.get("sku_id", ""))
    new_price = args.get("new_price")
    if not sku_id or not isinstance(new_price, int) or new_price <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "审批参数缺失：需要 sku_id 与正整数 new_price")
    sku, _ = await _get_sku(db, tenant, sku_id)
    sku.sale_price = new_price
    await _sync_knowledge_by_product_id(db, tenant=tenant, product_id=sku.product_id, actor=actor)


async def update_sku(
    db: AsyncSession,
    *,
    tenant: str,
    sku_id: str,
    barcode: str | None = None,
    status: str | None = None,
    actor: str = "",
) -> tuple[Sku, dict[str, Any]]:
    """行内编辑条码/上下架，返回 (SKU, 同步后的知识条目)。

    注意：**不含价格字段**——售价变更必须走 submit_price_change（审批红线）。
    """
    sku, product = await _get_sku(db, tenant, sku_id)
    if status is not None:
        if status not in SKU_STATUS_LABELS:
            raise BusinessError(ErrorCode.PARAM_INVALID, f"SKU 状态非法：{status}（可选 on/off）")
        sku.status = status
    if barcode is not None:
        sku.barcode = barcode.strip()
    kb_doc = await _sync_knowledge_by_product_id(
        db, tenant=tenant, product_id=product.id, actor=actor
    )
    await db.commit()
    return sku, kb_doc


async def set_goods_status(
    db: AsyncSession, *, tenant: str, product_id: str, status: str, actor: str = ""
) -> tuple[Product, dict[str, Any]]:
    """SPU 上下架（下架需前端二次确认，后端只校验状态合法性）。"""
    if status not in GOODS_STATUSES:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"商品状态非法：{status}（可选 {'/'.join(GOODS_STATUSES)}）"
        )
    product = await _get_product(db, tenant, product_id)
    product.status = status
    kb_doc = await _sync_knowledge_by_product_id(
        db, tenant=tenant, product_id=product_id, actor=actor
    )
    await db.commit()
    return product, kb_doc
