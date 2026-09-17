"""种子数据（首次启动幂等灌入，对齐数据模型与存储设计.md §6 迁移节）

链路：main.lifespan（SEED_ON_START）/ scripts/init_db.py → seed_on_startup()（基线：账号 + 租户行
     + B 端演示 + 知识库 29 篇 + Prompt v1）+ seed_closed_loop_demo()（页面闭环演示，见下）。
租户/用户名/密码/角色一律走 Settings（.env 可覆盖），禁止硬编码；生产置 SEED_ON_START=false。
B 端演示数据由 B2B_SEED_DEMO 控制（商品/SKU/仓库/库存/订单/一条待审改价），已存在商品即跳过。
闭环演示数据（会话/消息/工具调用/成本/审计/售后/营销/评价/工单/评测/回溯订单/坐席账号）
同由 B2B_SEED_DEMO 控制、已存在会话即跳过，保证前端删除 @/mock 后每个页面仍有真数据。
它**不进 seed_on_startup()**：单测靠基线种子断言精确条数（如「队列 total == 0」），
演示会话混进去会打挂断言，故只由 lifespan / scripts/init_db.py 显式调用。
知识库种子由 KB_SEED_DEMO/KB_SEED_DIR 控制（docs/knowledge-base 29 篇，SHA256 去重），已存在不覆盖。
本模块为入口编排：B 端演示常量与落库在 seed_b2b，闭环会话/运维记录在 seed_closed_loop，
业务记录（售后/营销/评价/工单/评测）在 seed_biz_records，并原样回导以保持 app.db.seed 公开 API 不变。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.security import hash_password
from app.db.models import Product, SalesOrder, Session, Sku, Tenant, User
from app.db.seed_b2b import _seed_backfill_orders, ensure_b2b_demo
from app.db.seed_biz_records import _seed_biz_records
from app.db.seed_closed_loop import _DEMO_AGENTS, _seed_ops_records, _seed_sessions
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


def _kb_seed_dir() -> Path | None:
    """种子目录：KB_SEED_DIR 相对仓库根（seed.py 上三级）；绝对路径直用；不存在返回 None。"""
    configured = Path(settings.KB_SEED_DIR)
    if configured.is_absolute():
        return configured if configured.is_dir() else None
    root = Path(__file__).resolve().parents[3]
    candidate = root / configured
    return candidate if candidate.is_dir() else None


async def ensure_kb_seed(db: AsyncSession) -> bool:
    """幂等灌企业知识库种子（docs/knowledge-base 29 篇，SHA256 去重）。

    元数据（密级/渠道/生效期/版本）只在新建时落库，已存在绝不覆盖人工编辑；
    镜像内无种子目录时静默跳过（容器部署走 GHCR 制品，不管仓库 docs）。
    """
    if not settings.KB_SEED_DEMO:
        return False
    from app.services import document_service

    seed_dir = _kb_seed_dir()
    if seed_dir is None:
        return False
    tenant = settings.SEED_TENANT
    created = 0
    for path in sorted(seed_dir.glob("*.md")):
        meta = document_service.parse_seed_markdown(path.read_text(encoding="utf-8"))
        if not meta["body"].strip():
            continue
        row, skipped = await document_service.get_or_create_doc(
            db,
            tenant=tenant,
            title=meta["title"] or path.stem,
            content=meta["body"],
            raw=meta["body"].encode("utf-8"),
            topic=meta.get("topic", ""),
            status="published",
        )
        if skipped:
            continue
        row.channels = json.dumps(meta["channels"], ensure_ascii=False)
        if meta["security_level"] in document_service.LEVELS:
            row.security_level = meta["security_level"]
        row.valid_from = meta["valid_from"]
        row.valid_to = meta["valid_to"]
        if meta["version"] > 1:
            row.version = meta["version"]
        created += 1
    if created:
        await db.commit()
    return created > 0


async def ensure_prompt_seed(db: AsyncSession) -> bool:
    """幂等灌 Prompt 种子版本（租户无任何版本时建 v1 online，内容 = 代码常量口径）。

    种子只解决「空租户对话链有线上版本可用」；运营后续新建/发布/回滚全走 Studio，
    已存在版本（哪怕被归档）即不再补种，不覆盖人工运维。
    """
    from app.db.models import PromptVersion
    from app.services.chat_prompt import DEFAULT_SYSTEM_PROMPT
    from app.services.studio_service import extract_variables

    tenant = settings.SEED_TENANT
    existed = (
        await db.execute(select(PromptVersion.id).where(PromptVersion.tenant == tenant).limit(1))
    ).scalar_one_or_none()
    if existed is not None:
        return False
    db.add(
        PromptVersion(
            tenant=tenant,
            version="v1",
            desc="种子线上版（与代码常量同文）",
            content=DEFAULT_SYSTEM_PROMPT,
            variables=json.dumps(extract_variables(DEFAULT_SYSTEM_PROMPT), ensure_ascii=False),
            gray=100,
            status="online",
            created_by="seed",
        )
    )
    await db.commit()
    return True


async def ensure_closed_loop_demo(db: AsyncSession) -> bool:
    """幂等灌「闭环演示数据」：一次让全部页面都有真实 DB 数据（前端无 mock 兜底）。

    幂等判据：本租户 sessions 表已有数据即整体跳过（含 B2B_SEED_DEMO=false 时）。
    依赖：需在 ensure_seed_user / ensure_seed_tenant / ensure_b2b_demo 之后调用
    （坐席账号挂租户、售后单挂已有订单、回溯订单挂已有 SKU）。
    """
    if not settings.B2B_SEED_DEMO:
        return False
    tenant = settings.SEED_TENANT
    username = settings.SEED_USERNAME
    existing = (
        await db.execute(select(func.count()).select_from(Session).where(Session.tenant == tenant))
    ).scalar_one()
    if existing:
        return False

    for name, roles, _note in _DEMO_AGENTS:
        found = (
            await db.execute(select(User).where(User.tenant == tenant, User.username == name))
        ).scalar_one_or_none()
        if found is None:
            db.add(
                User(
                    tenant=tenant,
                    username=name,
                    pwd_hash=hash_password(settings.SEED_PASSWORD.get_secret_value()),
                    roles=roles,
                )
            )
    await db.flush()

    skus = list(
        (await db.execute(select(Sku).where(Sku.tenant == tenant).order_by(Sku.id))).scalars()
    )
    spu_of: dict[str, str] = {}
    for pid, spu_no in (
        await db.execute(select(Product.id, Product.spu_no).where(Product.tenant == tenant))
    ).all():
        spu_of[str(pid)] = str(spu_no)
    orders: list[SalesOrder] = []
    if skus:
        orders = await _seed_backfill_orders(db, tenant=tenant, skus=skus, spu_of=spu_of)
    orders.extend(
        list(
            (
                await db.execute(
                    select(SalesOrder)
                    .where(SalesOrder.tenant == tenant)
                    .order_by(SalesOrder.created_at.desc())
                )
            ).scalars()
        )
    )

    sessions_results = await _seed_sessions(db, tenant=tenant, username=username)
    await _seed_ops_records(db, tenant=tenant, username=username, sessions_results=sessions_results)
    await _seed_biz_records(db, tenant=tenant, orders=orders)
    await db.commit()
    return True


async def seed_closed_loop_demo() -> bool:
    """页面闭环演示入口（lifespan / scripts/init_db.py 调用）：自建会话灌一次，有写入即 True。

    刻意独立于 seed_on_startup()：单测只跑基线种子，演示会话一旦混入会打挂
    「队列 total == 0」「绩效 items == []」这类精确条数断言。
    """
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        return await ensure_closed_loop_demo(db)


async def seed_on_startup() -> bool:
    """lifespan 调用入口：自建会话灌种子（账号 + 租户行 + B 端演示 + 知识库 29 篇），任一有写入即返回 True。"""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        user_created = await ensure_seed_user(db)
        tenant_created = await ensure_seed_tenant(db)
        demo_created = await ensure_b2b_demo(db)
        kb_created = await ensure_kb_seed(db)
        prompt_created = await ensure_prompt_seed(db)
    return user_created or tenant_created or demo_created or kb_created or prompt_created
