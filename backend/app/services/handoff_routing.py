"""转人工路由与接管（C 步余项：抢接/转接/技能门禁/排队位/智能分配/坐席负载，FRD FR-7）

职责：回答「谁能接、怎么接、排第几、谁最闲」——挂起判据在 handoff_rules、挂起动作在
      handoff_service；本模块管会话进队列之后的接管与路由：claim/transfer 带技能门禁，
      assign 按「技能匹配 + 在手最少 + 未达上限」智能分配，pending_positions 排队位，
      load_view 负载面板。
红线：技能组口径唯一出处在 handoff_rules（agent_skills/can_claim/skill_label），
     本模块不另建一套；claim/assign 共用「条件 UPDATE + rowcount」原子语义，
     并发接管不互相覆盖；只 flush 不 commit 由调用方统一提交。
对齐：API 规范 §4.11、FRD FR-7、数据模型 §2 sessions.handoff_skill。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record
from app.core.user_context import CurrentUser
from app.db.base import _now
from app.db.models import Session, User
from app.services import handoff_rules


async def _session_or_404(db: AsyncSession, *, tenant: str, session_id: str) -> Session:
    """租户内取会话行（跨租户/不存在 404 不泄露存在性；与 workbench_service 同语义）。"""
    row = (
        await db.execute(select(Session).where(Session.id == session_id, Session.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    return row


async def claim(db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str) -> Session:
    """抢接（pending/none→handling + assignee=本人；已被他人认领 1001 明示只读围观）。

    并发安全：认领用「条件 UPDATE + rowcount」做原子比较交换，两个坐席同抢同一会话时
    只有一个 UPDATE 命中（另一人 rowcount=0 → 重读后拿到「已被 XX 接管」），不会互相覆盖。
    自己已认领的会话重复点认领 = 幂等刷新（updated_at 前移），不报错。
    技能门禁（FR-7 技能组）：会话 handoff_skill 不在坐席可接组内 → 1001 明示缺哪个组；
    admin/* 恒全组，general 人人可接（口径唯一出处 handoff_rules.can_claim）。
    """
    row = await _session_or_404(db, tenant=tenant, session_id=session_id)
    if row.handoff_status == "resolved":
        raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可认领", 400)
    if not handoff_rules.can_claim(user.roles, row.handoff_skill or "general"):
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"该会话属「{handoff_rules.skill_label(row.handoff_skill or '')}」技能组，"
            f"您的账号未开通该组（找管理员加 cs:{row.handoff_skill} 角色）",
            400,
        )
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        update(Session)
        .where(
            Session.id == session_id,
            Session.tenant == tenant,
            or_(
                Session.handoff_status.in_(("pending", "none")),
                (Session.handoff_status == "handling")
                & (Session.assignee.in_(("", user.username))),
            ),
        )
        .values(handoff_status="handling", assignee=user.username, updated_at=_now())
    )
    if result.rowcount == 0:
        # 抢接失败：会话已被他人接管（或状态在读取后被改），重读拿真实归属再报错
        await db.rollback()
        current = await _session_or_404(db, tenant=tenant, session_id=session_id)
        if current.handoff_status == "resolved":
            raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可认领", 400)
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"已被 {current.assignee or '其他坐席'} 接管，转为只读围观",
            400,
        )
    await db.commit()
    await db.refresh(row)
    # 接起事件（E 步可观测）：observability 据此算「挂起→接起」耗时 = 30s 接起率分母/分子
    record(
        "handoff.claim",
        {"tenant": tenant, "session_id": session_id, "assignee": user.username},
    )
    return row


async def transfer(
    db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str, assignee: str
) -> Session:
    """转接（assignee 必填；pending 顺手进入 handling；已解决不可转）。

    技能门禁同 claim：目标坐席在本租户且角色可解析时，其技能组必须覆盖会话组，
    否则转过去也接不动（1001 明示缺组，不静默转成死单）。
    """
    target = (assignee or "").strip()
    if not target:
        raise BusinessError(ErrorCode.PARAM_INVALID, "转接坐席不能为空", 400)
    row = await _session_or_404(db, tenant=tenant, session_id=session_id)
    if row.handoff_status == "resolved":
        raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可转接", 400)
    skill = row.handoff_skill or "general"
    if skill != "general":
        from app.core.security import split_roles

        target_row = (
            await db.execute(select(User).where(User.tenant == tenant, User.username == target))
        ).scalar_one_or_none()
        if target_row is not None and not handoff_rules.can_claim(
            split_roles(target_row.roles or ""), skill
        ):
            raise BusinessError(
                ErrorCode.PARAM_INVALID,
                f"{target} 未开通「{handoff_rules.skill_label(skill)}」技能组，转接会被卡认领",
                400,
            )
    row.assignee = target
    if row.handoff_status == "pending":
        row.handoff_status = "handling"
    await db.commit()
    return row


async def pending_positions(db: AsyncSession, *, tenant: str, skill: str) -> dict[str, int]:
    """待接会话排队位（1 起，播报用）：同租户同技能组的 pending 按等待时长正序排。

    先挂起的排前面（FIFO），技能组隔离后各排各的队；非 pending 行不入表。
    """
    stmt = select(Session.id).where(Session.tenant == tenant, Session.handoff_status == "pending")
    if skill:
        stmt = stmt.where(Session.handoff_skill == skill)
    ids = list(
        (
            await db.execute(stmt.order_by(Session.updated_at.asc(), Session.created_at.asc()))
        ).scalars()
    )
    return {sid: index + 1 for index, sid in enumerate(ids)}


async def agent_loads(db: AsyncSession, *, tenant: str) -> dict[str, int]:
    """各坐席在手（handling）会话数：assignee → count（无在手的不在表里=0）。"""
    rows = await db.execute(
        select(Session.assignee, func.count())
        .where(Session.tenant == tenant, Session.handoff_status == "handling")
        .group_by(Session.assignee)
    )
    return {str(name or ""): int(count) for name, count in rows.all() if name}


async def tenant_agents(db: AsyncSession, *, tenant: str) -> list[tuple[str, set[str]]]:
    """本租户可接坐席清单（username, 技能组集合）：cs/admin/* 角色者；口径同 is_agent。"""
    from app.core.security import split_roles

    users = list(
        (
            await db.execute(select(User).where(User.tenant == tenant).order_by(User.username))
        ).scalars()
    )
    agents: list[tuple[str, set[str]]] = []
    for u in users:
        roles = split_roles(u.roles or "")
        if "*" in roles or "admin" in roles or "cs" in roles:
            agents.append((u.username, handoff_rules.agent_skills(roles)))
    return agents


async def assign(db: AsyncSession, *, tenant: str, user: CurrentUser, session_id: str) -> Session:
    """智能分配：给 pending 会话按「技能匹配 + 在手最少 + 未达上限」挑坐席并直接接管。

    口径（FR-7 负载均衡）：HANDOFF_LOAD_LIMIT=0 即关闭（1001 提示手动抢接）；
    候选=本租户坐席 ∩ 技能覆盖会话组；在手数并列取用户名小者（确定性）；
    全员达上限/无匹配 → 1001 明示原因，会话留在队列不硬塞。
    接管动作与坐席抢接同一把原子锁（条件 UPDATE pending→handling），并发分配不双派。
    """
    limit = int(settings.HANDOFF_LOAD_LIMIT or 0)
    if limit <= 0:
        raise BusinessError(ErrorCode.PARAM_INVALID, "智能分配已关闭（上限 0），请手动抢接", 400)
    row = await _pending_or_reject(db, tenant=tenant, session_id=session_id)
    skill = row.handoff_skill or "general"
    loads = await agent_loads(db, tenant=tenant)
    agents = await tenant_agents(db, tenant=tenant)
    candidates = [n for n, s in agents if skill in s and loads.get(n, 0) < limit]
    if not candidates:
        capable = [n for n, s in agents if skill in s]
        reason = (
            "该技能组坐席均在满载"
            if capable
            else f"无坐席开通「{handoff_rules.skill_label(skill)}」技能组"
        )
        raise BusinessError(ErrorCode.PARAM_INVALID, f"暂无可分配坐席：{reason}", 400)
    picked = min(candidates, key=lambda name: (loads.get(name, 0), name))
    result: CursorResult = await db.execute(  # type: ignore[assignment]
        update(Session)
        .where(
            Session.id == session_id,
            Session.tenant == tenant,
            Session.handoff_status.in_(("pending", "none")),
        )
        .values(handoff_status="handling", assignee=picked, updated_at=_now())
    )
    if result.rowcount == 0:
        await db.rollback()
        current = (
            await db.execute(
                select(Session).where(Session.id == session_id, Session.tenant == tenant)
            )
        ).scalar_one()
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            f"已被 {current.assignee or '其他坐席'} 接管，转为只读围观",
            400,
        )
    await db.commit()
    await db.refresh(row)
    record(
        "handoff.assign",
        {
            "tenant": tenant,
            "session_id": session_id,
            "assignee": picked,
            "skill": skill,
            "actor": user.username,
        },
    )
    return row


async def load_view(db: AsyncSession, *, tenant: str) -> dict[str, Any]:
    """坐席负载视图（GET /workbench/load）：各坐席在手数/上限/技能组 + 各组待接数。

    口径：assignee 计数走 DB 实况（与 metrics 队列存量同源）；技能组清单取
    Settings.HANDOFF_SKILL_GROUPS，待接数按组聚合（空组归 general）。
    """
    limit = int(settings.HANDOFF_LOAD_LIMIT or 0)
    loads = await agent_loads(db, tenant=tenant)
    agents = [
        {
            "username": name,
            "handling": loads.get(name, 0),
            "limit": limit,
            "at_capacity": limit > 0 and loads.get(name, 0) >= limit,
            "skills": sorted(skills),
        }
        for name, skills in await tenant_agents(db, tenant=tenant)
    ]
    pending_rows = await db.execute(
        select(Session.handoff_skill, func.count())
        .where(Session.tenant == tenant, Session.handoff_status == "pending")
        .group_by(Session.handoff_skill)
    )
    pending_by_skill = {str(skill or "general"): int(count) for skill, count in pending_rows.all()}
    return {
        "limit": limit,
        "enabled": limit > 0,
        "agents": agents,
        "pending_by_skill": pending_by_skill,
        "skill_groups": [
            {"key": g, "label": handoff_rules.skill_label(g)} for g in handoff_rules.skill_groups()
        ],
    }


async def _pending_or_reject(db: AsyncSession, *, tenant: str, session_id: str) -> Session:
    """分配前置校验：会话在本租户且未解决/未被接管，否则 1001/404。"""
    row = (
        await db.execute(select(Session).where(Session.id == session_id, Session.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "会话不存在或已过期", 404)
    if row.handoff_status == "resolved":
        raise BusinessError(ErrorCode.PARAM_INVALID, "会话已解决，不可分配", 400)
    if row.handoff_status == "handling":
        raise BusinessError(ErrorCode.PARAM_INVALID, f"已由 {row.assignee} 接管，无需分配", 400)
    return row
