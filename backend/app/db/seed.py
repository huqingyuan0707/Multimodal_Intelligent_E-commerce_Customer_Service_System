"""种子数据（首次启动幂等灌入，对齐数据模型与存储设计.md §6 迁移节）

链路：main.lifespan（SEED_ON_START）/ scripts/init_db.py → ensure_seed_user() + ensure_b2b_demo()。
租户/用户名/密码/角色一律走 Settings（.env 可覆盖），禁止硬编码；生产置 SEED_ON_START=false。
B 端演示数据由 B2B_SEED_DEMO 控制（商品/SKU/仓库/库存/订单/一条待审改价），已存在商品即跳过。
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.security import hash_password
from app.db.models import (
    Approval,
    Inventory,
    LogisticsOrder,
    Product,
    SalesOrder,
    Sku,
    Tenant,
    User,
    Warehouse,
)
from app.db.session import get_engine


async def ensure_seed_user(db: AsyncSession) -> bool:
    """幂等灌种子：不存在则建；已存在则只并集补齐缺失角色（不动密码）。

    原因：SEED_ROLES 随版本加新权限时，存量 dev 库账号否则永远 403；
    密码绝不覆盖，生产 SEED_ON_START=false 此函数不执行。
    """
    from app.core.security import split_roles

    tenant = settings.SEED_TENANT
    username = settings.SEED_USERNAME
    exists = (
        await db.execute(select(User).where(User.tenant == tenant, User.username == username))
    ).scalar_one_or_none()
    if exists is not None:
        wanted = split_roles(settings.SEED_ROLES)
        have = split_roles(exists.roles)
        missing = [r for r in wanted if r not in have]
        if not missing:
            return False
        exists.roles = settings.ROLES_SEPARATOR.join([*have, *missing])
        await db.commit()
        return True
    db.add(
        User(
            tenant=tenant,
            username=username,
            pwd_hash=hash_password(settings.SEED_PASSWORD.get_secret_value()),
            roles=settings.SEED_ROLES,
        )
    )
    await db.commit()
    return True


@dataclass(frozen=True)
class _DemoProduct:
    """演示 SPU：variants 为 (颜色, 尺码) 组合，default_stock 为 (中心仓, 华东仓) 常规数量。"""

    spu_no: str
    name: str
    category: str
    attrs: dict[str, str]
    variants: tuple[tuple[str, str], ...]
    list_price: int
    sale_price: int
    default_stock: tuple[int, int]


@dataclass(frozen=True)
class _DemoOrder:
    """演示订单：lines 为 (spu_no, 颜色, 尺码, 件数)，waybill 非空表示已发货并带面单。"""

    platform: str
    outer_id: str
    status: str
    lines: tuple[tuple[str, str, str, int], ...]
    waybill: tuple[str, str] | None = None


# 扩展属性（材质/洗涤方式）是 workbench 属性卡的数据源，值必须写实。
_DEMO_PRODUCTS: tuple[_DemoProduct, ...] = (
    _DemoProduct(
        spu_no="TSIRT-001",
        name="重磅纯棉短袖 T 恤",
        category="男装/T恤",
        attrs={"材质": "100% 棉 260g 重磅", "洗涤方式": "机洗 30℃，不可漂白，阴凉处晾干"},
        variants=tuple(
            (color, size) for color in ("白", "黑", "雾蓝") for size in ("S", "M", "L", "XL")
        ),
        list_price=19900,
        sale_price=12900,
        default_stock=(80, 30),
    ),
    _DemoProduct(
        spu_no="HOODIE-002",
        name="加绒连帽卫衣",
        category="男装/卫衣",
        attrs={"材质": "棉 70% 涤 30%，内里加绒", "洗涤方式": "反面机洗 30℃，不可烘干"},
        variants=tuple((color, size) for color in ("米白", "咖啡") for size in ("M", "L", "XL")),
        list_price=39900,
        sale_price=29900,
        default_stock=(40, 15),
    ),
)

# 个别 SKU 刻意做成「低于安全线 / 断货 / 有占用」，让 /inventory 首屏就能演示预警与可用量公式：
# key = f"{spu_no}-{color}-{size}" → (中心仓 qty, 华东仓 qty, reserved, locked)
_DEMO_STOCK: dict[str, tuple[int, int, int, int]] = {
    "TSIRT-001-白-M": (6, 4, 2, 0),
    "TSIRT-001-黑-L": (0, 0, 0, 0),
    "HOODIE-002-米白-M": (12, 6, 5, 2),
}

# 三种状态覆盖订单状态机分支：待发货（可打单）/ 待付款（不可发货）/ 已发货（可售后）
_DEMO_ORDERS: tuple[_DemoOrder, ...] = (
    _DemoOrder(
        platform="taobao",
        outer_id="TB20260912001",
        status="paid",
        lines=(("TSIRT-001", "白", "M", 1), ("TSIRT-001", "黑", "L", 2)),
    ),
    _DemoOrder(
        platform="douyin",
        outer_id="DY20260912002",
        status="pending_pay",
        lines=(("HOODIE-002", "咖啡", "M", 1),),
    ),
    _DemoOrder(
        platform="weixin",
        outer_id="WX20260911003",
        status="shipped",
        lines=(("TSIRT-001", "雾蓝", "S", 1),),
        waybill=("顺丰", "SF1234567890"),
    ),
)


def _barcode(key: str) -> str:
    """确定性条码（69 前缀 + 11 位）：用 crc32 而非 hash()，后者跨进程随机化会导致数据不稳定。"""
    return f"69{zlib.crc32(key.encode()) % 10**11:011d}"


async def ensure_b2b_demo(db: AsyncSession) -> bool:
    """幂等灌 B 端演示数据（商品/SKU 矩阵、双仓库存、三种状态订单、一条待审改价）。

    幂等判据：本租户 products 表已有数据即跳过；生产把 B2B_SEED_DEMO 置 false。
    """
    if not settings.B2B_SEED_DEMO:
        return False
    tenant = settings.SEED_TENANT
    existing = (
        await db.execute(select(func.count()).select_from(Product).where(Product.tenant == tenant))
    ).scalar_one()
    if existing:
        return False

    center = Warehouse(tenant=tenant, name="中心仓")
    east = Warehouse(tenant=tenant, name="华东仓")
    db.add_all([center, east])
    await db.flush()

    skus: dict[str, Sku] = {}
    for spec in _DEMO_PRODUCTS:
        product = Product(
            tenant=tenant,
            spu_no=spec.spu_no,
            name=spec.name,
            category=spec.category,
            attrs=json.dumps(spec.attrs, ensure_ascii=False),
            status="on",
        )
        db.add(product)
        await db.flush()
        for color, size in spec.variants:
            key = f"{spec.spu_no}-{color}-{size}"
            sku = Sku(
                tenant=tenant,
                product_id=product.id,
                color=color,
                size=size,
                barcode=_barcode(key),
                list_price=spec.list_price,
                sale_price=spec.sale_price,
            )
            db.add(sku)
            await db.flush()
            skus[key] = sku
            qty_center, qty_east, reserved, locked = _DEMO_STOCK.get(
                key, (spec.default_stock[0], spec.default_stock[1], 0, 0)
            )
            db.add_all(
                [
                    Inventory(
                        tenant=tenant,
                        warehouse_id=center.id,
                        sku_id=sku.id,
                        qty=qty_center,
                        reserved=reserved,
                        warn_line=settings.STOCK_WARN_DEFAULT,
                    ),
                    Inventory(
                        tenant=tenant,
                        warehouse_id=east.id,
                        sku_id=sku.id,
                        qty=qty_east,
                        locked=locked,
                        warn_line=settings.STOCK_WARN_DEFAULT,
                    ),
                ]
            )

    for order_spec in _DEMO_ORDERS:
        items: list[dict[str, object]] = []
        total = 0
        for spu_no, color, size, qty in order_spec.lines:
            sku = skus[f"{spu_no}-{color}-{size}"]
            items.append(
                {
                    "sku_id": sku.id,
                    "sku_code": f"{spu_no}-{color}-{size}",
                    "color": color,
                    "size": size,
                    "qty": qty,
                    "price": sku.sale_price,
                }
            )
            total += sku.sale_price * qty
        order = SalesOrder(
            tenant=tenant,
            platform=order_spec.platform,
            outer_id=order_spec.outer_id,
            items=json.dumps(items, ensure_ascii=False),
            total=total,
            status=order_spec.status,
        )
        db.add(order)
        await db.flush()
        if order_spec.waybill is not None:
            db.add(
                LogisticsOrder(
                    tenant=tenant,
                    sales_order_id=order.id,
                    company=order_spec.waybill[0],
                    tracking_no=order_spec.waybill[1],
                )
            )

    # 一条待审改价：让审批中心首屏有真实待办（演示「改价恒进审批」红线）
    demo_sku = skus.get("TSIRT-001-白-M")
    if demo_sku is not None:
        db.add(
            Approval(
                tenant=tenant,
                action="sku.price_change",
                target=f"TSIRT-001 重磅纯棉短袖 T 恤｜白/M（{demo_sku.id}）",
                args=json.dumps({"sku_id": demo_sku.id, "new_price": 11900}),
                reason="9 月大促报名要求降至 119 元",
                applicant=settings.SEED_USERNAME,
            )
        )
    await db.commit()
    return True


async def ensure_seed_tenant(db: AsyncSession) -> bool:
    """幂等灌种子租户行（code 与 SEED_TENANT 同源，供 /admin 首屏有数据）。"""
    tenant = settings.SEED_TENANT.strip()
    existed = (await db.execute(select(Tenant).where(Tenant.code == tenant))).scalar_one_or_none()
    if existed is not None:
        return False
    db.add(
        Tenant(
            code=tenant,
            name="演示租户",
            plan="trial",
            quota_tokens=settings.DEFAULT_QUOTA_TOKENS,
            quota_concurrency=settings.DEFAULT_QUOTA_CONCURRENCY,
        )
    )
    await db.commit()
    return True


async def seed_on_startup() -> bool:
    """lifespan 调用入口：自建会话灌种子（账号 + 租户行 + B 端演示数据），任一有写入即返回 True。"""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        user_created = await ensure_seed_user(db)
        tenant_created = await ensure_seed_tenant(db)
        demo_created = await ensure_b2b_demo(db)
    return user_created or tenant_created or demo_created
