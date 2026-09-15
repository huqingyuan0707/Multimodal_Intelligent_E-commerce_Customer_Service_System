"""黄金集评估流水线（FR-9 / 测试评估验收方案 §5，对齐 RAG 规范 §4 口径）

链路：seed/golden_set.tsv（200 条）→ 临时库灌 29 篇种子 → 逐条走线上同款检索
      （knowledge_service.retrieve 三路召回+治理）→ 分场景算指标 → PASS/FAIL + RESULT。
指标口径：grounded（可答题命中预期资料）；幻觉（拒答题被抬进引用）；自动解决率仅网关模式
      统计（真答 + guard.pass + grounded）。两档判定：棘轮基线（CI 防退化）与
      FRD 验收线（发布门禁）——离线词法检索段先如实亮出与验收线的差距，不粉饰。
模式：默认 retrieval（纯检索，无外部依赖，CI 可跑）；--gateway 追加 chat_service.answer
      真模型作答（Ollama 不可用自动跳过生成段指标，绝不报错中断——降级红线同款）。
用法（backend/ 目录）：python scripts/eval_golden.py [--gateway] [tsv路径]
口径声明：本流水线先于真实运营数据建立「指标可证」的基线；LLM-as-judge 与人工抽检
      为后续增量（执行步骤 E），当前自动判定全部来自检索/引用校验的确定性信号。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import ensure_kb_seed
from app.db.session import get_engine, init_models
from app.services import chat_service, knowledge_service

DEFAULT_TSV = BACKEND / "seed" / "golden_set.tsv"
TENANT = "demo-tenant"
ROLES = ["cs"]

# 指标口径（测试评估验收方案 §5 / FRD §8 验收表，两档）：
# 验收线 = FRD 生产发布标准；棘轮线 = 当前已验证基线，CI 阻断「退化」不阻断「未达标」。
# BGE 向量 + bge-reranker + 输入域守卫接入后，棘轮逐档收紧到验收线（执行步骤 E/P1）。
ACCEPT_GROUNDED_MIN = 0.95  # 可答题命中预期资料的底线（FRD 验收）
ACCEPT_HALLUCINATION_MAX = 0.02  # 拒答题被抬进引用的上限（FRD 验收）
ACCEPT_AUTO_RESOLVE_MIN = 0.80  # 网关模式自动解决率底线（FRD 验收）
BASE_GROUNDED_MIN = 0.85  # 棘轮：低于已验证基线即回归，CI 红
BASE_HALLUCINATION_MAX = 0.80  # 棘轮：拒答泄漏率基线 0.775（离线检索段，无域守卫）


def load_samples(tsv: Path) -> list[dict[str, Any]]:
    """读黄金集 TSV：id/scene/query/expect_titles/expect_refuse 五列，表头跳过。"""
    lines = tsv.read_text(encoding="utf-8").splitlines()
    samples: list[dict[str, Any]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        sid, scene, query, expect, refuse = line.split("\t")
        samples.append(
            {
                "id": sid,
                "scene": scene,
                "query": query,
                "expect_titles": json.loads(expect),
                "expect_refuse": refuse == "true",
            }
        )
    return samples


async def _eval_db(tmp_dir: Path) -> AsyncSession:
    """临时 SQLite 库 + 29 篇种子（与 test_rag_chain 同口径，评估环境不碰 dev.db）。"""
    session_mod.settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_dir / 'golden-eval.db'}"
    settings.KB_SEED_DIR = str(BACKEND.parents[0] / "docs" / "knowledge-base")
    session_mod._engine = None
    session_mod._SessionFactory = None
    await init_models()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    db = factory()
    assert await ensure_kb_seed(db), "种子知识库灌入失败（检查 docs/knowledge-base）"
    return db


def _score(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总指标（纯函数）：grounded / 幻觉（误答率）/ 分场景明细。"""
    answerable = [s for s in samples if not s["expect_refuse"]]
    refuse = [s for s in samples if s["expect_refuse"]]
    grounded = sum(1 for s in answerable if s.get("hit"))
    # 拒答题 hit=True 是「正确空手」；被抬进引用（hit=False）才是幻觉
    hallucinated = sum(1 for s in refuse if not s.get("hit"))
    resolved = sum(1 for s in answerable if s.get("resolved"))
    per_scene: dict[str, dict[str, int]] = {}
    for s in samples:
        cell = per_scene.setdefault(s["scene"], {"total": 0, "hit": 0})
        cell["total"] += 1
        cell["hit"] += 1 if s.get("hit") else 0
    n_ans, n_ref = len(answerable), len(refuse)
    return {
        "total": len(samples),
        "answerable": n_ans,
        "refuse": n_ref,
        "grounded": round(grounded / n_ans, 4) if n_ans else 0.0,
        "hallucination": round(hallucinated / n_ref, 4) if n_ref else 0.0,
        "auto_resolved": round(resolved / n_ans, 4) if n_ans else 0.0,
        "per_scene": per_scene,
        "misses": [
            {
                "id": s["id"],
                "scene": s["scene"],
                "query": s["query"],
                "expect": s["expect_titles"],
                "got": s.get("got_titles", []),
                "why": "expected_not_retrieved" if not s["expect_refuse"] else "should_refuse",
            }
            for s in samples
            if not s.get("hit")
        ],
    }


async def _run_one(db: AsyncSession, sample: dict[str, Any], gateway: bool) -> None:
    """单样本判定：检索命中预期资料=hit；网关模式再走 answer 统计 resolved（真答+guard.pass）。"""
    refs = await knowledge_service.retrieve(
        sample["query"], TENANT, db=db, roles=ROLES, trace_id=f"eval-{sample['id']}"
    )
    titles = [str(r.get("title", "")) for r in refs]
    expect = set(sample["expect_titles"])
    if sample["expect_refuse"]:
        sample["hit"] = not titles  # 拒答题：检索必须空手（空→端点 2001）
    else:
        sample["hit"] = bool(expect & set(titles))
    sample["got_titles"] = titles[:3]
    if gateway and not sample["expect_refuse"]:
        sample["resolved"] = False
        try:
            result = await chat_service.answer(sample["query"], db=db, roles=ROLES)
            guard: object = result.get("guard", {})
            passed = bool(guard.get("pass")) if isinstance(guard, dict) else False
            sample["resolved"] = passed and bool(expect & set(titles))
        except chat_service.NoEvidenceError:
            pass  # 有据样本被拒答：不算 resolved，由 hits 段暴露
        except Exception as exc:
            sample["gateway_error"] = str(exc)[:120]


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gateway = "--gateway" in sys.argv[1:]
    tsv = Path(args[0]) if args else DEFAULT_TSV
    samples = load_samples(tsv)
    mode = "gateway（检索+真模型作答）" if gateway else "retrieval（纯检索）"
    print(f"黄金集：{len(samples)} 条（{tsv.name}），模式={mode}")
    print(f"场景分布：{dict(Counter(s['scene'] for s in samples))}")

    set_current_user(CurrentUser(username="golden-eval", tenant=TENANT, roles=ROLES))
    import tempfile

    with tempfile.TemporaryDirectory(prefix="golden-eval-", ignore_cleanup_errors=True) as tmp:
        db = await _eval_db(Path(tmp))
        started = time.perf_counter()
        try:
            for s in samples:
                await _run_one(db, s, gateway)
        finally:
            await db.close()
            # aiosqlite 持有文件句柄：不 dispose 则 Windows 上临时库删不掉
            await get_engine().dispose()
            session_mod._engine = None
            session_mod._SessionFactory = None
            set_current_user(None)
    elapsed = time.perf_counter() - started

    score = _score(samples)
    print(
        f"grounded={score['grounded']:.3f}（验收≥{ACCEPT_GROUNDED_MIN} 棘轮≥{BASE_GROUNDED_MIN}） "
        f"幻觉率={score['hallucination']:.3f}（验收≤{ACCEPT_HALLUCINATION_MAX} "
        f"棘轮≤{BASE_HALLUCINATION_MAX}） 耗时={elapsed:.1f}s"
    )
    for scene, cell in sorted(score["per_scene"].items()):
        rate = cell["hit"] / cell["total"] if cell["total"] else 0.0
        print(f"  {scene}：{cell['hit']}/{cell['total']}（{rate:.3f}）")
    if gateway:
        errs = sum(1 for s in samples if "gateway_error" in s)
        print(
            f"自动解决率={score['auto_resolved']:.3f}（≥{ACCEPT_AUTO_RESOLVE_MIN}） "
            f"网关异常样本={errs}（异常不中断，计未解决）"
        )
    if score["misses"]:
        print(f"未达标样本 {len(score['misses'])} 条：")
        for m in score["misses"][:20]:
            print(
                f"  {m['id']} [{m['scene']}] {m['query']} → {m['why']} "
                f"期望={m['expect']} 实得={m['got']}"
            )
        if len(score["misses"]) > 20:
            print(f"  ……其余 {len(score['misses']) - 20} 条见报告文件")

    report = BACKEND / "data" / "golden-eval" / f"report-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {"mode": mode, "score": score, "samples": samples}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    print(f"报告：{report}")

    # 棘轮（CI 阻断）：任何指标低于当前基线即红；验收（发布门禁）：两档全达 FRD 线才算达标
    ratchet_ok = score["grounded"] >= BASE_GROUNDED_MIN and score["hallucination"] <= (
        BASE_HALLUCINATION_MAX
    )
    accept_ok = score["grounded"] >= ACCEPT_GROUNDED_MIN and score["hallucination"] <= (
        ACCEPT_HALLUCINATION_MAX
    )
    if gateway:
        ratchet_ok = ratchet_ok and score["auto_resolved"] >= ACCEPT_AUTO_RESOLVE_MIN
        accept_ok = accept_ok and score["auto_resolved"] >= ACCEPT_AUTO_RESOLVE_MIN
    if accept_ok:
        verdict = "PASS（达 FRD 验收线）"
    elif ratchet_ok:
        verdict = "PASS（棘轮基线达标；验收线未达，见上差距——BGE/rerank/域守卫为收紧路径）"
    else:
        verdict = "FAIL（指标较基线退化）"
    print(f"RESULT: {verdict}")
    return 0 if ratchet_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
