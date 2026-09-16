"""转人工触发规则表单测（C 步：规则优先级 / 阈值边界 / 连续计数 / 总开关，对齐 FRD FR-7）

链路：纯逻辑直测（不建库、不起服务）——`handoff_rules` 是全站唯一的挂起判据来源，
      本文件保证「哪条规则先命中、阈值边界、连续计数何时清零」不被后续改动改坏。
运行（backend/ 目录）：pytest tests/test_handoff_rules.py
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import handoff_rules


def test_rule_table_shape() -> None:
    """规则表自身规整：code 唯一、priority 升序、reason 中文非空（坐席要看得懂）。"""
    codes = [rule.code for rule in handoff_rules.RULES]
    assert len(codes) == len(set(codes))
    priorities = [rule.priority for rule in handoff_rules.RULES]
    assert priorities == sorted(priorities)
    for rule in handoff_rules.RULES:
        assert rule.reason.strip()
        assert any("\u4e00" <= char <= "\u9fff" for char in rule.reason)


@pytest.mark.parametrize(
    ("signal", "code"),
    [
        ("explicit_request", "explicit_request"),
        ("negative_sentiment", "negative_sentiment"),
        ("approval_pending", "sensitive_approval"),
        ("vision_need_human", "vision_low_confidence"),
        ("no_evidence", "no_evidence"),
        ("agent_no_result", "agent_no_result"),
        ("tool_empty", "tool_empty"),
    ],
)
def test_boolean_rules(signal: str, code: str) -> None:
    """每条布尔规则单独给信号都能命中，且只回自己这一条。"""
    decision = handoff_rules.evaluate({signal: True})
    assert decision["hit"] is True
    assert decision["code"] == code
    assert decision["reason"]
    assert decision["matched"] == [code]
    assert decision["enabled"] is True


def test_no_signal_no_hit() -> None:
    """没有任何信号 = 不打扰人工，返回形状仍然齐全（调用方可直接透出）。"""
    blank = handoff_rules.evaluate({})
    assert blank["hit"] is False
    assert blank["code"] == "" and blank["reason"] == ""
    assert blank["matched"] == [] and blank["matched_rules"] == []


def test_miss_streak_threshold_boundary() -> None:
    """「连续不懂」边界：阈值前一轮不命中，达阈值命中且 reason 带实际次数。"""
    threshold = settings.HANDOFF_MISS_STREAK_THRESHOLD
    assert threshold >= 1
    assert handoff_rules.evaluate({"miss_streak": threshold - 1})["hit"] is False
    hit = handoff_rules.evaluate({"miss_streak": threshold})
    assert hit["code"] == "miss_streak"
    assert str(threshold) in hit["reason"]


def test_zero_threshold_disables_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """阈值置 0 = 关闭该规则（判定不命中，规则表视图里 enabled=false 可解释）。"""
    monkeypatch.setattr(settings, "HANDOFF_MISS_STREAK_THRESHOLD", 0)
    assert handoff_rules.evaluate({"miss_streak": 99})["hit"] is False
    rows = {row["code"]: row for row in handoff_rules.rule_table()}
    assert rows["miss_streak"]["enabled"] is False
    assert rows["no_evidence"]["enabled"] is True


def test_priority_first_wins() -> None:
    """同时命中多条：挂起取优先级最高者，其余落 matched 供审计。"""
    decision = handoff_rules.evaluate(
        {"explicit_request": True, "no_evidence": True, "tool_empty": True}
    )
    assert decision["code"] == "explicit_request"
    assert decision["matched"][:3] == ["explicit_request", "no_evidence", "tool_empty"]
    assert len(decision["matched_rules"]) == 3


def test_query_drives_keyword_rules() -> None:
    """买家原话自动带出喊人工 / 情绪信号（调用方只传 query 即可）。"""
    assert (
        handoff_rules.evaluate({"query": "你们能不能转人工处理一下"})["code"] == "explicit_request"
    )
    assert handoff_rules.evaluate({"query": "这质量也太差了！！"})["code"] == "negative_sentiment"


def test_disabled_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """总开关关闭：规则表不判命（显式动作仍可改流转态，由端点负责）。"""
    monkeypatch.setattr(settings, "HANDOFF_ENABLED", False)
    decision = handoff_rules.evaluate({"query": "转人工", "no_evidence": True})
    assert decision["hit"] is False
    assert decision["enabled"] is False
    assert all(row["enabled"] is False for row in handoff_rules.rule_table())


def test_detect_helpers() -> None:
    """关键词与情绪助手：命中即真，空文本与无关文本恒假。"""
    assert handoff_rules.detect_human_request("麻烦转人工") is True
    assert handoff_rules.detect_human_request("") is False
    assert handoff_rules.detect_human_request("这个多少钱") is False
    assert handoff_rules.detect_negative_sentiment("我要投诉你们") is True
    assert handoff_rules.detect_negative_sentiment("太慢了！！") is True
    assert handoff_rules.detect_negative_sentiment("包裹到了吗") is False


def test_streak_counts_and_resets() -> None:
    """连续计数：遇人工代回（by=agent）立即清零，混入正常轮也会断开。"""
    assert handoff_rules.missed_streak([{"rejected": True}, {"rejected": True}]) == 2
    assert handoff_rules.missed_streak([{"empty": True}, {"rejected": True}]) == 2
    assert handoff_rules.missed_streak([{"empty": True}, {"pass": True}, {"rejected": True}]) == 1
    assert (
        handoff_rules.missed_streak(
            [{"by": "agent"}, {"rejected": True}, {"rejected": True}, {"rejected": True}]
        )
        == 0
    )
    assert handoff_rules.streak([{"degraded": True}, {"degraded": True}], "degraded") == 2
    assert handoff_rules.streak([{"degraded": True}, {"pass": True}], "degraded") == 1


def test_rule_table_rows_carry_threshold() -> None:
    """规则表视图给前端/坐席看：阈值型规则带当前阈值，布尔规则阈值为 0。"""
    rows = {row["code"]: row for row in handoff_rules.rule_table()}
    assert rows["miss_streak"]["threshold"] == settings.HANDOFF_MISS_STREAK_THRESHOLD
    assert rows["degrade_streak"]["threshold"] == settings.HANDOFF_DEGRADE_STREAK_THRESHOLD
    assert rows["no_evidence"]["threshold"] == 0
    assert {row["code"] for row in handoff_rules.rule_table()} == set(handoff_rules.RULE_BY_CODE)


# ---------------- 技能组路由（FR-7 技能组） ----------------


def test_rules_carry_skill_group() -> None:
    """每条规则都挂组且在合法清单内；专组规则路由正确（情绪→投诉、退款→退款、图检→售后）。"""
    groups = set(handoff_rules.skill_groups())
    for rule in handoff_rules.RULES:
        assert rule.skill in groups
    by_code = {rule.code: rule.skill for rule in handoff_rules.RULES}
    assert by_code["negative_sentiment"] == "complaint"
    assert by_code["sensitive_approval"] == "refund"
    assert by_code["vision_low_confidence"] == "aftersale"
    assert by_code["explicit_request"] == "general"


def test_evaluate_returns_skill_of_hit_rule() -> None:
    """命中决策透出该规则的技能组（挂起时写进 sessions.handoff_skill 的路由来源）。"""
    assert handoff_rules.evaluate({"approval_pending": True})["skill"] == "refund"
    assert handoff_rules.evaluate({"no_evidence": True})["skill"] == "general"
    assert handoff_rules.evaluate({})["skill"] == ""


def test_agent_skills_and_claim_gate() -> None:
    """坐席技能解析与认领门禁：cs:<组> 令牌、general 人人可接、admin/* 恒全组。"""
    refund_only = ["cs", "cs:refund"]
    assert handoff_rules.agent_skills(refund_only) == {"general", "refund"}
    assert handoff_rules.can_claim(refund_only, "refund") is True
    assert handoff_rules.can_claim(refund_only, "complaint") is False
    assert handoff_rules.can_claim(refund_only, "general") is True
    assert handoff_rules.can_claim(refund_only, "") is True  # 未路由放行
    assert handoff_rules.can_claim(["*"], "complaint") is True
    assert handoff_rules.can_claim(["admin"], "complaint") is True
    assert handoff_rules.can_claim(["cs"], "complaint") is False  # 只有 cs 无组标=仅通用


def test_skill_label_and_groups_from_settings() -> None:
    """组清单读 Settings（逗号串也认）；标签中文可坐席直读。"""
    assert "general" in handoff_rules.skill_groups()
    assert handoff_rules.skill_label("refund") == "退款售后"
    assert handoff_rules.skill_label("unknown_key") == "unknown_key"
