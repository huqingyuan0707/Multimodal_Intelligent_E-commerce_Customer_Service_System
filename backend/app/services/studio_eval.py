"""Agent Studio 评测 runs（采样判定 + 双档 verdict，对齐 FRD FR-3/页面设计 §3.6）

链路：endpoints/studio 建 run → BackgroundTasks 调本模块 run_eval
      → 取黄金集前 limit 条 → _judge_sample 两道闸（守卫→检索）
      → summarize_eval 双档 verdict 落库 done。
红线：查询强制带 tenant；采样跑在本租户真实知识库上；任何异常只落
      failed + error 并记可观测，绝不外抛；阈值/TSV 解析延迟 import
      scripts.eval_golden（顶层引会与 chat_service 成环）。
"""

from __future__ import annotations

import contextlib
import json
import time
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError, ErrorCode
from app.core.observability import record
from app.core.user_context import CurrentUser, set_current_user
from app.db.models import EvalRun
from app.services import guard_service, knowledge_service

EVAL_STATUSES = ("pending", "running", "done", "failed")

EVAL_DEFAULT_NAME = "default-200"
EVAL_DEFAULT_LIMIT = 50
EVAL_LIMIT_MAX = 200


def eval_to_dict(row: EvalRun) -> dict[str, Any]:
    """评测 run 出参（score 解析失败即空形状，前端红条按 pass=false 处理）。"""
    try:
        score = json.loads(row.score or "{}")
        score = score if isinstance(score, dict) else {}
    except ValueError:
        score = {}
    return {
        "id": row.id,
        "name": row.name or EVAL_DEFAULT_NAME,
        "limit": int(row.limit or 0),
        "status": row.status or "pending",
        "score": score,
        "pass": bool(score.get("ratchet_ok", False)),
        "accept": bool(score.get("accept_ok", False)),
        "elapsed_ms": int(row.elapsed_ms or 0),
        "error": row.error or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds")
        if row.created_at
        else "",
    }


async def create_eval_run(
    db: AsyncSession, *, tenant: str, name: str = "", limit: int = 0, by: str
) -> dict[str, Any]:
    """建评测 run（pending 即返；真正执行由 BackgroundTasks 调 run_eval）。"""
    size = limit if 1 <= limit <= EVAL_LIMIT_MAX else EVAL_DEFAULT_LIMIT
    row = EvalRun(
        tenant=tenant,
        name=(name or "").strip() or EVAL_DEFAULT_NAME,
        limit=size,
        status="pending",
        created_by=by,
    )
    db.add(row)
    await db.commit()
    return eval_to_dict(row)


async def list_eval_runs(
    db: AsyncSession, *, tenant: str, page: int = 1, size: int = 20
) -> dict[str, Any]:
    """评测历史（创建时间倒序；分页对象与版本列表同口径）。"""
    stmt = select(EvalRun).where(EvalRun.tenant == tenant)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (
        (
            await db.execute(
                stmt.order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [eval_to_dict(row) for row in rows],
        "total": total,
        "page": page,
        "size": size,
    }


async def get_eval_run(db: AsyncSession, *, tenant: str, run_id: str) -> dict[str, Any]:
    """评测 run 详情（跨租户/不存在 404，不泄露存在性）。"""
    row = (
        await db.execute(select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "评测任务不存在或已过期", 404)
    return eval_to_dict(row)


async def latest_accept_ok(db: AsyncSession, *, tenant: str) -> bool:
    """本租户最近一次 done 评测是否达验收线（一次没跑过即 False）。"""
    row = (
        (
            await db.execute(
                select(EvalRun)
                .where(EvalRun.tenant == tenant, EvalRun.status == "done")
                .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return False
    try:
        score = json.loads(row.score or "{}")
    except ValueError:
        return False
    return bool(score.get("accept_ok", False))


def summarize_eval(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总指标（纯函数）：口径与 scripts/eval_golden._score 一致，并扩展 guard 分布。

    每样本需字段：scene/query/expect_titles/expect_refuse/hit/got_titles/guard；
    guard 分布统计被守卫拦下的样本按 category 计数（页面设计 §3.6「guard 分布」）。
    """
    answerable = [s for s in samples if not s.get("expect_refuse")]
    refuse = [s for s in samples if s.get("expect_refuse")]
    grounded = sum(1 for s in answerable if s.get("hit"))
    hallucinated = sum(1 for s in refuse if not s.get("hit"))
    per_scene: dict[str, dict[str, int]] = {}
    guard_dist: Counter[str] = Counter()
    for sample in samples:
        cell = per_scene.setdefault(str(sample.get("scene", "")), {"total": 0, "hit": 0})
        cell["total"] += 1
        if sample.get("hit"):
            cell["hit"] += 1
        if sample.get("guard"):
            guard_dist[str(sample["guard"])] += 1
    n_ans, n_ref = len(answerable), len(refuse)
    return {
        "total": len(samples),
        "answerable": n_ans,
        "refuse": n_ref,
        "grounded": round(grounded / n_ans, 4) if n_ans else 0.0,
        "hallucination": round(hallucinated / n_ref, 4) if n_ref else 0.0,
        "per_scene": per_scene,
        "guard_dist": dict(guard_dist),
        "misses": [
            {
                "id": s.get("id", ""),
                "scene": s.get("scene", ""),
                "query": s.get("query", ""),
                "expect": s.get("expect_titles", []),
                "got": s.get("got_titles", []),
            }
            for s in samples
            if not s.get("hit")
        ][:20],
    }


async def _judge_sample(
    db: AsyncSession, *, tenant: str, sample: dict[str, Any], roles: list[str]
) -> None:
    """单样本判定（与 eval_golden 同款两道闸：先守卫，再线上检索；拒答题空手即 hit）。

    采样跑在本租户真实知识库上，指标含义是「当前线上知识实测」，
    前端展示采样数以避免与全量脚本口径混读。
    """
    verdict = guard_service.check(str(sample.get("query", "")))
    if verdict["refuse"]:
        sample["guard"] = str(verdict["category"])
        sample["hit"] = bool(sample.get("expect_refuse"))
        if not sample.get("expect_refuse"):
            sample["got_titles"] = ["GUARD-BLOCKED"]
        return
    refs = await knowledge_service.retrieve(
        str(sample.get("query", "")),
        tenant,
        db=db,
        roles=roles,
        trace_id=f"studio-eval-{sample.get('id', '')}",
    )
    titles = [str(r.get("title", "")) for r in refs]
    expect = set(sample.get("expect_titles", []))
    if sample.get("expect_refuse"):
        sample["hit"] = not titles
    else:
        sample["hit"] = bool(expect & set(titles))
    sample["got_titles"] = titles[:3]


async def run_eval(*, tenant: str, run_id: str, by: str = "") -> None:
    """评测后台执行入口（BackgroundTasks 用；自建会话，请求会话已关闭）。

    流程：pending→running → 取前 limit 条黄金集 → 逐条两道闸判定 →
    双档 verdict 落库 done；任何异常落 failed + error，绝不外抛。
    阈值/TSV 解析延迟 import scripts.eval_golden（模块顶层引会与
    chat_service 形成导入环；此处调用时各模块早已加载完毕）。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import get_engine

    started = time.perf_counter()
    try:
        from scripts.eval_golden import (
            ACCEPT_GROUNDED_MIN,
            ACCEPT_HALLUCINATION_MAX,
            BASE_GROUNDED_MIN,
            BASE_HALLUCINATION_MAX,
            DEFAULT_TSV,
            load_samples,
        )

        maker = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with maker() as db:
            set_current_user(CurrentUser(username=by or "studio-eval", tenant=tenant, roles=["cs"]))
            row = (
                await db.execute(
                    select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant == tenant)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = "running"
            await db.commit()
            samples = load_samples(DEFAULT_TSV)[: max(1, int(row.limit or EVAL_DEFAULT_LIMIT))]
            for sample in samples:
                await _judge_sample(db, tenant=tenant, sample=sample, roles=["cs"])
            score = summarize_eval(samples)
            score["ratchet_ok"] = bool(
                score["grounded"] >= BASE_GROUNDED_MIN
                and score["hallucination"] <= BASE_HALLUCINATION_MAX
            )
            score["accept_ok"] = bool(
                score["grounded"] >= ACCEPT_GROUNDED_MIN
                and score["hallucination"] <= ACCEPT_HALLUCINATION_MAX
            )
            row.score = json.dumps(score, ensure_ascii=False)
            row.status = "done"
            row.error = ""
            row.elapsed_ms = int((time.perf_counter() - started) * 1000)
            await db.commit()
    except Exception as exc:
        try:
            maker = async_sessionmaker(get_engine(), expire_on_commit=False)
            async with maker() as db:
                row = (
                    await db.execute(
                        select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant == tenant)
                    )
                ).scalar_one_or_none()
                if row is not None:
                    row.status = "failed"
                    row.error = str(exc)[:500]
                    row.elapsed_ms = int((time.perf_counter() - started) * 1000)
                    await db.commit()
        except Exception:
            pass
        record("studio.eval", {"tenant": tenant, "run_id": run_id, "error": str(exc)[:200]})
    finally:
        with contextlib.suppress(Exception):
            set_current_user(None)
