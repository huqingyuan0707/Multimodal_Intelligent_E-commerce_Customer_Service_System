"""组织服务（排班 / 绩效到人 / 离职冻结，对齐 FRD FR-12.4 + 页面设计 §3.19）

链路：/admin 组织窗格 → 本模块 → shifts（排班）+ sessions/session_scores（绩效到人）
      + users.status（离职冻结）→ 全部写操作同步记 audit_logs。

口径：
- **技能组取值复用 `handoff_rules.HANDOFF_SKILL_GROUPS`**（唯一出处）：排班与队列路由必须同一套组名，
  否则会出现「排了班却接不到该组的会话」这种查不出来的错配。
- **绩效到人 = 坐席维度聚合**：只含坐席工号与聚合指标，不含任何买家标识（订单号/手机号/地址）——
  这就是「绩效到人（PII 脱敏）」的落地方式；要买家信息的场景另走有权限的页面。
- **冻结 = `users.status=frozen`（拒登但保留行）**：会话/绩效/审计都还要回溯到人，删账号会断引用。
  两条防锁死保护：不能冻结自己、不能冻结本租户最后一个启用中的管理员。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.db.models import Session, SessionScore, Shift, User
from app.services.admin_service import USER_STATUS_LABELS, dt_text, record_audit
from app.services.handoff_rules import skill_groups, skill_label

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def shift_to_dict(row: Shift) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant": row.tenant,
        "username": row.username,
        "work_date": row.work_date,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "skill": row.skill,
        "skill_label": skill_label(row.skill),
        "note": row.note,
        "created_at": dt_text(row.created_at),
    }


def _validate_shift(
    username: str, work_date: str, start_time: str, end_time: str, skill: str
) -> tuple[str, str, str, str, str]:
    person = (username or "").strip()
    if not person:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择排班坐席")
    day = (work_date or "").strip()
    if not _DATE_RE.match(day):
        raise BusinessError(ErrorCode.PARAM_INVALID, "排班日期格式应为 YYYY-MM-DD")
    start = (start_time or "").strip()
    end = (end_time or "").strip()
    if not _TIME_RE.match(start) or not _TIME_RE.match(end):
        raise BusinessError(ErrorCode.PARAM_INVALID, "起止时间格式应为 HH:MM（24 小时制）")
    if start >= end:
        raise BusinessError(ErrorCode.PARAM_INVALID, "结束时间必须晚于开始时间")
    if skill not in skill_groups():
        raise BusinessError(
            ErrorCode.PARAM_INVALID, f"技能组非法：{skill}（可选：{'/'.join(skill_groups())}）"
        )
    return person, day, start, end, skill


async def list_shifts(
    db: AsyncSession,
    *,
    tenant: str = "",
    username: str = "",
    work_date: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """排班分页（按日期倒序；可筛坐席/日期）。"""
    if work_date.strip() and not _DATE_RE.match(work_date.strip()):
        raise BusinessError(ErrorCode.PARAM_INVALID, "排班日期格式应为 YYYY-MM-DD")
    stmt = select(Shift)
    if tenant.strip():
        stmt = stmt.where(Shift.tenant == tenant.strip())
    if username.strip():
        stmt = stmt.where(Shift.username == username.strip())
    if work_date.strip():
        stmt = stmt.where(Shift.work_date == work_date.strip())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(Shift.work_date.desc(), Shift.start_time)
                .offset((page - 1) * size)
                .limit(size)
            )
        ).scalars()
    )
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [shift_to_dict(row) for row in rows],
        "skills": [{"value": item, "label": skill_label(item)} for item in skill_groups()],
    }


async def create_shift(
    db: AsyncSession,
    *,
    tenant: str,
    username: str,
    work_date: str,
    start_time: str = "09:00",
    end_time: str = "18:00",
    skill: str = "general",
    note: str = "",
    actor: str = "",
) -> Shift:
    """登记一段班（同人同日同技能组时段重叠不校验 —— 交班/顶班允许，由排班人自己把关）。"""
    cleaned_tenant = (tenant or "").strip()
    if not cleaned_tenant:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择排班所属租户")
    person, day, start, end, skill = _validate_shift(
        username, work_date, start_time, end_time, skill
    )
    existed = (
        await db.execute(select(User).where(User.tenant == cleaned_tenant, User.username == person))
    ).scalar_one_or_none()
    if existed is None:
        raise BusinessError(ErrorCode.NOT_FOUND, f"该租户下没有这个坐席：{person}", 404)
    row = Shift(
        tenant=cleaned_tenant,
        username=person,
        work_date=day,
        start_time=start,
        end_time=end,
        skill=skill,
        note=(note or "")[:200],
    )
    db.add(row)
    await db.flush()
    await record_audit(
        db,
        tenant=cleaned_tenant,
        actor=actor,
        action="shift.create",
        target=f"{person}@{day}",
        detail={"start": start, "end": end, "skill": skill},
    )
    await db.commit()
    return row


async def delete_shift(db: AsyncSession, *, shift_id: str, actor: str = "") -> None:
    """删一段班（破坏性操作，前端须二次确认）。"""
    row = (await db.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "排班记录不存在", 404)
    detail = {"username": row.username, "work_date": row.work_date, "skill": row.skill}
    tenant = row.tenant
    await db.delete(row)
    await db.flush()
    await record_audit(
        db,
        tenant=tenant,
        actor=actor,
        action="shift.delete",
        target=f"{detail['username']}@{detail['work_date']}",
        detail=detail,
    )
    await db.commit()


async def performance(
    db: AsyncSession,
    *,
    tenant: str,
    username: str = "",
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """坐席绩效到人（质检均分 + 接手量 + 解决量）——只含坐席工号，不含买家标识。"""
    cleaned_tenant = (tenant or "").strip()
    if not cleaned_tenant:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择租户")
    sessions_row = (
        await db.execute(
            select(
                Session.assignee,
                func.count(Session.id),
                func.sum(case((Session.handoff_status == "resolved", 1), else_=0)),
            )
            .where(Session.tenant == cleaned_tenant, Session.assignee != "")
            .group_by(Session.assignee)
        )
    ).all()
    scores_row = (
        await db.execute(
            select(SessionScore.assignee, func.avg(SessionScore.score), func.count(SessionScore.id))
            .where(SessionScore.tenant == cleaned_tenant, SessionScore.assignee != "")
            .group_by(SessionScore.assignee)
        )
    ).all()
    scores = {str(name): (float(avg or 0), int(count or 0)) for name, avg, count in scores_row}

    items: list[dict[str, Any]] = []
    for name, handled, resolved in sessions_row:
        person = str(name)
        avg_score, scored = scores.get(person, (0.0, 0))
        handled_int = int(handled or 0)
        resolved_int = int(resolved or 0)
        items.append(
            {
                "username": person,
                "handled": handled_int,
                "resolved": resolved_int,
                # 解决率分母用「接手过的会话数」，不拿全租户当分母（口径写在这里，前端照抄展示）
                "resolve_rate": (round(resolved_int / handled_int, 4) if handled_int else None),
                "avg_score": (round(avg_score, 2) if scored else None),
                "scored_sessions": scored,
                "no_score": scored == 0,
            }
        )
    items.sort(key=lambda item: (-item["handled"], item["username"]))
    if username.strip():
        items = [item for item in items if item["username"] == username.strip()]
    total = len(items)
    return {
        "items": items[(page - 1) * size : page * size],
        "total": total,
        "page": page,
        "size": size,
        "privacy_note": "本报表只含坐席工号与聚合指标，不含买家标识（订单号/手机号/地址）",
        "scope_note": "解决率分母为该坐席接手过的会话数；质检分为 session_scores 均分",
    }


async def set_frozen(db: AsyncSession, *, user_id: str, frozen: bool, actor: str = "") -> User:
    """离职冻结/解冻（拒登但保留行）。两条防锁死保护见模块 docstring。"""
    row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "用户不存在", 404)
    if frozen:
        if row.username == actor:
            raise BusinessError(ErrorCode.PARAM_INVALID, "不能冻结当前登录账号（会把自己锁在门外）")
        roles = [item.strip() for item in (row.roles or "").split(",") if item.strip()]
        if "admin" in roles or "*" in roles:
            alive = (
                await db.execute(
                    select(func.count())
                    .select_from(User)
                    .where(
                        User.tenant == row.tenant,
                        User.status == "active",
                        User.roles.like("%admin%"),
                    )
                )
            ).scalar_one()
            if int(alive or 0) <= 1:
                raise BusinessError(
                    ErrorCode.PARAM_INVALID, "该用户是本租户唯一启用中的管理员，冻结后将无人可管"
                )
    new_status = "frozen" if frozen else "active"
    old_status = row.status or "active"
    row.status = new_status
    await db.flush()
    await record_audit(
        db,
        tenant=row.tenant,
        actor=actor,
        action="user.freeze" if frozen else "user.unfreeze",
        target=row.username,
        detail={"from": old_status, "to": new_status},
    )
    await db.commit()
    return row


def user_status_label(status: str) -> str:
    """用户状态中文（用户列表与冻结操作共用同一份口径，映射表在 admin_service）。"""
    return USER_STATUS_LABELS.get(status or "active", status or "active")
