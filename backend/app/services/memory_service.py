"""跨会话短期记忆 + 长期偏好（FR-4/FR-1.4 收官，对齐数据模型 §4 键规范 + 后端工程化 §七）

链路：_begin_turn → recall（偏好/近况拼块进 history：摘要→偏好→近况→窗口）；
      _persist_agent_turn → record_turn（规则抽取→短期 Redis 24h 滑动 / 长期 PG 显式授权落库）；
      delete_session → forget_thread；DELETE /auth/me/memory → forget_user（一键遗忘）。
键口径 (tenant, Token 用户名, thread) 与鉴权同源：
  sess:{tenant}:{username}:{thread} = 线程快照{updated_at, block, stats, summary}（24h 滑动）
  mem:{tenant}:{username} = 跨会话近况{facts}（24h 滑动）
红线：PII 永不进记忆（core.pii 守门）；长期写入仅显式"记住"授权 + MEMORY_LONG_ENABLED；
      记忆读写失败只降级跳过（日志留痕），绝不打断对话落库。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import cache
from app.core.pii import contains_pii
from app.db.models import UserPreference

logger = logging.getLogger(__name__)

# ---------------- 键 ----------------


def thread_key(tenant: str, username: str, thread: str) -> str:
    """线程快照键（数据模型 §4 短期记忆行，消息窗口+摘要）。"""
    return f"sess:{tenant}:{username}:{thread}"


def user_key(tenant: str, username: str) -> str:
    """跨会话近况键（本任务新增行，见数据模型 §4 用户事实 24h 滑动）。"""
    return f"mem:{tenant}:{username}"


# ---------------- 事实抽取（规则版，PII 守门） ----------------

FACT_LABELS: dict[str, str] = {
    "height_cm": "身高",
    "weight_kg": "体重",
    "bust_cm": "胸围",
    "waist_cm": "腰围",
    "hip_cm": "臀围",
    "fit": "版型偏好",
    "budget_cny": "预算",
    "size": "尺码",
}

_FIT_MAP = {"修身": "修身", "常规": "常规", "宽松": "宽松", "oversize": "宽松", "大版型": "宽松"}

_EXPLICIT = re.compile(r"记住|以后都|下次|偏好|习惯")


def _num(raw: str, low: float, high: float) -> float | None:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if low <= val <= high else None


def extract_facts(text: str) -> dict[str, str]:
    """从用户陈述抽事实（纯函数）：仅白名单键 + 数值范围校验 + 值级 PII 守门。

    身高/体重支持"身高180体重65"双填启发式（140-210 + 35-150 才认，避免误吞单号）。
    """
    facts: dict[str, str] = {}
    src = text or ""

    def put(key: str, value: str) -> None:
        value = (value or "").strip()[:24]
        if value and key not in facts and not contains_pii(value):
            facts[key] = value

    m = re.search(r"身高\D{0,6}(\d{2,3})", src)
    if m and _num(m.group(1), 100, 250) is not None:
        put("height_cm", f"{int(float(m.group(1)))}cm")
    m = re.search(r"体重\D{0,6}(\d{2,3}(?:\.\d)?)\s*(kg|公斤|斤)?", src)
    if m and _num(m.group(1), 20, 300) is not None:
        kilo = float(m.group(1)) / 2 if m.group(2) == "斤" else float(m.group(1))
        put("weight_kg", f"{int(kilo) if kilo.is_integer() else round(kilo, 1)}kg")
    if "height_cm" not in facts or "weight_kg" not in facts:
        m = re.search(r"(\d{3})\s*[，,、\s]+\s*(\d{2,3})\s*(kg|公斤|斤)?", src)
        if m and _num(m.group(1), 140, 210) is not None and _num(m.group(2), 35, 150) is not None:
            put("height_cm", f"{m.group(1)}cm")
            kilo = float(m.group(2)) / 2 if m.group(3) == "斤" else float(m.group(2))
            put("weight_kg", f"{int(kilo) if kilo.is_integer() else round(kilo, 1)}kg")
    for key, word in (("bust_cm", "胸围"), ("waist_cm", "腰围"), ("hip_cm", "臀围")):
        m = re.search(rf"{word}\D{{0,6}}(\d{{2,3}})", src)
        if m and _num(m.group(1), 40, 200) is not None:
            put(key, f"{m.group(1)}cm")
    m = re.search(r"(修身|常规|宽松|oversize|大版型)", src, re.IGNORECASE)
    if m:
        put("fit", _FIT_MAP.get(m.group(1).lower(), m.group(1)))
    m = re.search(r"预算\D{0,8}(\d{3,6})", src) or re.search(
        r"(\d{3,6})\s*元\s*(以内|以下|左右|上下|预算)?", src
    )
    if m and _num(m.group(1), 50, 1000000) is not None:
        put("budget_cny", f"{m.group(1)}元")
    m = re.search(r"(?:穿|尺码)\D{0,4}(XXS|XS|S|M|L|XL|XXL|3XL|均码)", src.upper())
    if m:
        put("size", m.group(1))
    return facts


def is_explicit_preference(text: str) -> bool:
    """是否为显式偏好授权（"记住/以后都/下次/偏好/习惯"出现即 True，纯函数）。"""
    return bool(_EXPLICIT.search(text or ""))


# ---------------- 召回渲染 ----------------


def render_recent(facts: dict[str, str]) -> str:
    """【用户近况】块（空 facts 回空串，调用方跳过）。"""
    lines = [f"{FACT_LABELS[k]}：{v}" for k, v in facts.items() if k in FACT_LABELS]
    return "【用户近况】\n" + "\n".join(lines) if lines else ""


def render_prefs(prefs: dict[str, str]) -> str:
    """【长期偏好】块（用户已确认记住，空回空串）。"""
    lines = [f"{FACT_LABELS[k]}：{v}" for k, v in prefs.items() if k in FACT_LABELS]
    return "【长期偏好】\n" + "\n".join(lines) if lines else ""


# ---------------- 短期：记录与召回 ----------------


async def record_turn(
    db: AsyncSession, *, tenant: str, username: str, query: str
) -> dict[str, int]:
    """轮次落库后记短期记忆 + 显式授权落长期偏好（_persist_agent_turn 调用）。

    失败只记日志跳过（不污染本轮事务提交）；返回 {"short","prefs"} 计数。
    """
    try:
        facts = extract_facts(query)
        if not facts:
            return {"short": 0, "prefs": 0}
        current = await cache.get_json(user_key(tenant, username)) or {}
        merged = {**(current.get("facts") or {}), **facts}
        await cache.set_json(
            user_key(tenant, username),
            {"facts": merged},
            settings.MEMORY_SHORT_TTL,
        )
        prefs = 0
        if is_explicit_preference(query) and settings.MEMORY_LONG_ENABLED:
            prefs = await _upsert_prefs(db, tenant=tenant, username=username, facts=facts)
        return {"short": len(facts), "prefs": prefs}
    except Exception:
        logger.warning("memory record skipped", exc_info=True)
        return {"short": 0, "prefs": 0}


async def _upsert_prefs(db: AsyncSession, *, tenant: str, username: str, facts: dict) -> int:
    """长期偏好原地覆盖（同键只一行；flush 不提交，由调用方事务收口）。"""
    count = 0
    for key, value in facts.items():
        if key not in FACT_LABELS:
            continue
        row = (
            await db.execute(
                select(UserPreference).where(
                    UserPreference.tenant == tenant,
                    UserPreference.username == username,
                    UserPreference.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(UserPreference(tenant=tenant, username=username, key=key, value=value))
        else:
            row.value = value
        count += 1
    if count:
        await db.flush()
    return count


async def recall_short(tenant: str, username: str) -> dict[str, str]:
    """读跨会话近况（miss/异常回空字典，绝不抛错）。"""
    try:
        data = await cache.get_json(user_key(tenant, username))
        facts = (data or {}).get("facts") or {}
        return {k: str(v) for k, v in facts.items() if k in FACT_LABELS}
    except Exception:
        logger.warning("memory recall skipped", exc_info=True)
        return {}


async def recall_prefs(db: AsyncSession, *, tenant: str, username: str) -> dict[str, str]:
    """读长期偏好（开关关闭回空；异常回空不阻断对话）。"""
    try:
        if not settings.MEMORY_LONG_ENABLED:
            return {}
        rows = list(
            (
                await db.execute(
                    select(UserPreference)
                    .where(UserPreference.tenant == tenant, UserPreference.username == username)
                    .order_by(UserPreference.updated_at.asc())
                )
            ).scalars()
        )
        return {r.key: r.value for r in rows if r.key in FACT_LABELS}
    except Exception:
        logger.warning("prefs recall skipped", exc_info=True)
        return {}


# ---------------- 线程快照（数据模型 §4 sess 键，消息窗口+摘要） ----------------


async def snapshot_read(
    tenant: str, username: str, thread: str, updated_at: str
) -> dict[str, Any] | None:
    """读线程快照：updated_at 对上才命中（touch_session 每轮刷新天然失效旧快照）。

    形状不对/过期/miss 一律回 None 走 PG 重建；绝不抛错。
    """
    try:
        snap = await cache.get_json(thread_key(tenant, username, thread))
        if not isinstance(snap, dict) or snap.get("updated_at") != updated_at:
            return None
        stats = snap.get("stats")
        if (
            not isinstance(snap.get("block"), str)
            or not isinstance(stats, dict)
            or not isinstance(snap.get("summary"), str)
        ):
            return None
        return {"block": snap["block"], "stats": dict(stats), "summary": snap["summary"]}
    except Exception:
        logger.warning("snapshot read skipped", exc_info=True)
        return None


async def snapshot_write(
    tenant: str,
    username: str,
    thread: str,
    *,
    updated_at: str,
    block: str,
    stats: dict[str, int],
    summary: str,
) -> None:
    """写线程快照（24h 滑动；失败静默，PG 才是真源）。"""
    try:
        await cache.set_json(
            thread_key(tenant, username, thread),
            {"updated_at": updated_at, "block": block, "stats": stats, "summary": summary},
            settings.MEMORY_SHORT_TTL,
        )
    except Exception:
        logger.warning("snapshot write skipped", exc_info=True)


# ---------------- 遗忘 ----------------


async def forget_thread(tenant: str, username: str, thread: str) -> None:
    """删会话清扫线程快照（delete_session 调用；cache.delete 本身不抛错）。"""
    await cache.delete(thread_key(tenant, username, thread))


async def forget_user(db: AsyncSession, *, tenant: str, username: str) -> dict[str, int]:
    """一键遗忘（GDPR/个保）：长期偏好按户清 + 近况键删 + 线程快照按前缀扫。

    审计留痕后同事务提交；会话消息原文不动（会话级遗忘走 DELETE sessions）。
    """
    from app.services import admin_service

    doomed = list(
        (
            await db.execute(
                select(UserPreference).where(
                    UserPreference.tenant == tenant, UserPreference.username == username
                )
            )
        ).scalars()
    )
    for row in doomed:
        await db.delete(row)
    await cache.delete(user_key(tenant, username))
    swept = await cache.scan_delete(f"sess:{tenant}:{username}:")
    await admin_service.record_audit(
        db,
        tenant=tenant,
        actor=username,
        action="memory.forget",
        target=username,
        detail={"prefs": len(doomed), "threads": swept},
    )
    await db.commit()
    return {"prefs": len(doomed), "threads": swept}
