"""质检打分与绩效单测（C 步收官：judge 解析 / 规则兜底 / 评分落库 / 绩效聚合，对齐 FRD FR-7）

链路：纯函数直测 + 临时库服务级直测（LLM 打桩：可用回 judge / 抛 LlmUnavailableError
      走 rule 兜底），端点形状走 test_workbench 集成用例。
运行（backend/ 目录）：pytest tests/test_quality.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.core.exceptions import BusinessError
from app.db import session as session_mod
from app.db.session import init_models
from app.services import llm_service, quality_service, session_service


def test_parse_judge_output_ok_and_reject() -> None:
    """judge 输出解析：正常 JSON 规整化；越界分/坏 JSON/多余文字包裹各有对策。"""
    good = quality_service.parse_judge_output(
        '```json\n{"score": 4, "resolution_ok": true, "dimensions": {"resolution": 5,'
        ' "accuracy": 4, "attitude": 4, "process": 3, "extra": 9}, "reason": "答复准确"}\n```'
    )
    assert good is not None
    assert good["score"] == 4 and good["resolution_ok"] is True
    assert set(good["dimensions"]) == {"resolution", "accuracy", "attitude", "process"}
    assert quality_service.parse_judge_output('{"score": 9}') is None  # 越界
    assert quality_service.parse_judge_output('{"score": "abc"}') is None  # 非数
    assert quality_service.parse_judge_output("模型没按格式回答") is None  # 无 JSON
    assert quality_service.parse_judge_output("") is None


def test_build_transcript_roles_and_truncation() -> None:
    """转写口径：user→买家 / 其余→客服，空内容跳过，超 QUALITY_MAX_MESSAGES 截尾段。"""
    msgs = [
        {"role": "user", "content": "退货"},
        {"role": "agent", "content": "已登记"},
        {"role": "user", "content": "  "},
    ]
    text = quality_service.build_transcript(msgs, "已按 15 天换货处理")
    assert text.startswith("买家：退货\n客服：已登记")
    assert "解决小结：已按 15 天换货处理" in text
    many = [{"role": "user", "content": f"m{i}"} for i in range(60)]
    assert (
        len(quality_service.build_transcript(many, "").splitlines())
        == settings.QUALITY_MAX_MESSAGES
    )


def test_rule_fallback_scoring() -> None:
    """规则兜底：有客服回复+小结=5；末轮拒答扣一分；无客服回复再扣。"""
    agent = [{"role": "user", "content": "q"}, {"role": "agent", "content": "a", "guard": "{}"}]
    assert quality_service.rule_fallback(agent, "已解决")["score"] == 5
    rejected = [
        {"role": "user", "content": "q"},
        {"role": "agent", "content": "a", "guard": '{"rejected": true}'},
    ]
    assert quality_service.rule_fallback(rejected, "已解决")["score"] == 4
    only_user = [{"role": "user", "content": "q"}]
    low = quality_service.rule_fallback(only_user, "")
    assert low["score"] == 2 and low["resolution_ok"] is False


async def test_score_session_judge_and_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """评分落库：judge 成功 source=judge；人工改评 source=manual+reviewer；越界 1001。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'q.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    gen = session_mod.get_db()
    db = await gen.__anext__()
    try:
        row = await session_service.create_session(db, tenant="t1", username="b1", title="质检")
        await session_service.save_user_message(db, tenant="t1", session_id=row.id, content="退货")
        await session_service.save_agent_message(
            db,
            tenant="t1",
            session_id=row.id,
            content="已登记换货",
            citations=[],
            guard={"pass": True},
            faithfulness=0.9,
            trace_id="tr-1",
        )
        await db.commit()

        async def fake_complete(
            messages: list[dict[str, str]], **kw: object
        ) -> llm_service.LlmReply:
            return llm_service.LlmReply(
                text='{"score": 4, "resolution_ok": true, "reason": "答复准确"}',
                model="stub",
                latency_ms=1,
            )

        monkeypatch.setattr(llm_service, "complete", fake_complete)
        judged = await quality_service.score_session(db, tenant="t1", session_id=row.id)
        assert (judged["score"], judged["source"], judged["pass"]) == (4, "judge", True)

        # 模型不可用 → 规则兜底（绝不抛）
        async def broken(messages: list[dict[str, str]], **kw: object) -> llm_service.LlmReply:
            raise llm_service.LlmUnavailableError("模型挂了")

        monkeypatch.setattr(llm_service, "complete", broken)
        fallback = await quality_service.score_session(db, tenant="t1", session_id=row.id)
        assert fallback["source"] == "rule" and 1 <= fallback["score"] <= 5

        # 人工改评：source=manual + reviewer 留痕；越界 1001
        manual = await quality_service.score_session(
            db,
            tenant="t1",
            session_id=row.id,
            manual={"score": 5, "resolution_ok": True, "comment": "坐席复核优秀"},
            reviewer="cs01",
        )
        assert (manual["source"], manual["reviewer"], manual["score"]) == ("manual", "cs01", 5)
        with pytest.raises(BusinessError) as bad:
            await quality_service.score_session(
                db, tenant="t1", session_id=row.id, manual={"score": 9}, reviewer="cs01"
            )
        assert bad.value.code == 1001

        # 绩效聚合：resolved+assignee 的会话进表，均分/通过率按 pass_score
        row.handoff_status = "resolved"
        row.assignee = "cs01"
        await db.commit()
        perf = await quality_service.performance_view(db, tenant="t1")
        agent = next(a for a in perf["agents"] if a["assignee"] == "cs01")
        assert agent["resolved"] == 1 and agent["scored"] == 1
        assert agent["avg_score"] == 5.0 and agent["pass_rate"] == 1.0
        assert agent["manual_reviews"] == 1
        assert perf["pass_score"] == settings.QUALITY_PASS_SCORE
    finally:
        await gen.aclose()


async def test_auto_score_skips_manual_and_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """后台自动评分：总开关关=不落库；已人工评=不覆盖。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'q2.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    gen = session_mod.get_db()
    db = await gen.__anext__()
    try:
        row = await session_service.create_session(db, tenant="t2", username="b2", title="自动评")
        await session_service.save_agent_message(
            db,
            tenant="t2",
            session_id=row.id,
            content="答过了",
            citations=[],
            guard={"pass": True},
            faithfulness=0.8,
            trace_id="tr-2",
        )
        await db.commit()

        monkeypatch.setattr(settings, "QUALITY_AUTO_SCORE", False)
        await quality_service.auto_score_session(tenant="t2", session_id=row.id)
        assert (await quality_service.get_score(db, tenant="t2", session_id=row.id))["score"] == 0

        monkeypatch.setattr(settings, "QUALITY_AUTO_SCORE", True)

        async def fake_complete(
            messages: list[dict[str, str]], **kw: object
        ) -> llm_service.LlmReply:
            return llm_service.LlmReply(
                text='{"score": 3, "resolution_ok": false}', model="s", latency_ms=1
            )

        monkeypatch.setattr(llm_service, "complete", fake_complete)
        await quality_service.auto_score_session(tenant="t2", session_id=row.id)
        first = await quality_service.get_score(db, tenant="t2", session_id=row.id)
        assert (first["score"], first["source"]) == (3, "judge")

        # 人工评后自动评不覆盖
        await quality_service.score_session(
            db, tenant="t2", session_id=row.id, manual={"score": 5}, reviewer="cs9"
        )
        await quality_service.auto_score_session(tenant="t2", session_id=row.id)
        kept = await quality_service.get_score(db, tenant="t2", session_id=row.id)
        assert (kept["score"], kept["source"]) == (5, "manual")
    finally:
        await gen.aclose()
