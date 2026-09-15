"""转人工触发规则表（FRD FR-7 / 执行步骤.md C 步「触发规则表」）

职责：把原先散落在 chat_service（拒答、图检低置信各自写死一句 reason）与 Agent runtime
（空手转人工）里的挂起判据，收成一份显式规则表——「什么情况转人工」全站只有这一处定义。
链路：chat_service / agent runtime 组 signals → handoff_service.auto_handoff()（补连续计数）
     → 本模块 evaluate() → 命中则 sessions.handoff_status: none→pending + handoff_reason。
红线：纯逻辑模块（不 import FastAPI 对象、不碰 DB 会话）；开关/词表/阈值一律读 settings，
     禁止在本文件里写死可调值；面向坐席的 reason 必须中文且可操作；命中多条时取优先级
     最高者挂起，其余落 matched 供审计与前端展示。
对齐：API接口与SSE事件协议规范.md §4.11、执行步骤.md §C、FRD FR-7、数据模型 §2 sessions.handoff_*。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class HandoffRule:
    """一条转人工规则。

    signal：signals 字典里的键名；布尔规则看真假，计数规则看数值。
    threshold_field：计数规则对应的 Settings 字段名，非空即为「阈值型」，
        此时 reason 里的 `{n}` 会被实际连续轮次替换。
    """

    code: str
    label: str
    reason: str
    priority: int
    signal: str
    threshold_field: str = ""


# 规则表（priority 越小越先命中）。新增规则只改这里 + Settings 阈值，挂载点不动。
RULES: tuple[HandoffRule, ...] = (
    HandoffRule(
        "explicit_request",
        "买家喊人工",
        "买家明确要求人工客服，已转人工接待",
        10,
        "explicit_request",
    ),
    HandoffRule(
        "negative_sentiment",
        "买家情绪激烈",
        "买家情绪激烈，已优先转人工安抚",
        20,
        "negative_sentiment",
    ),
    HandoffRule(
        "sensitive_approval",
        "敏感操作送审",
        "退款等敏感操作已提交审批，转人工确认",
        30,
        "approval_pending",
    ),
    HandoffRule(
        "vision_low_confidence",
        "图检低置信",
        "图片检测置信度不足，需人工复核",
        40,
        "vision_need_human",
    ),
    HandoffRule(
        "no_evidence", "无据拒答", "知识库未检索到权威依据，已转人工确认", 50, "no_evidence"
    ),
    HandoffRule(
        "agent_no_result", "编排未产出", "编排未拿到可用结果，转人工确认", 60, "agent_no_result"
    ),
    HandoffRule(
        "tool_empty", "业务系统无果", "业务系统未返回可用结果，已转人工跟进", 61, "tool_empty"
    ),
    HandoffRule(
        "miss_streak",
        "连续未解决",
        "连续 {n} 次未给出有效答复，已转人工",
        70,
        "miss_streak",
        "HANDOFF_MISS_STREAK_THRESHOLD",
    ),
    HandoffRule(
        "degrade_streak",
        "模型连续失败",
        "模型连续 {n} 次不可用，已转人工",
        80,
        "degrade_streak",
        "HANDOFF_DEGRADE_STREAK_THRESHOLD",
    ),
)

RULE_BY_CODE: dict[str, HandoffRule] = {rule.code: rule for rule in RULES}


def _words(value: Any) -> list[str]:
    """词表归一：.env 覆盖可能给逗号串（中文逗号也认），空串剔除。"""
    parts = value.replace("，", ",").split(",") if isinstance(value, str) else list(value or [])
    return [str(part).strip() for part in parts if str(part).strip()]


def _hit_keywords(text: str, words: list[str]) -> bool:
    """大小写不敏感的关键词命中（空文本恒不命中）。"""
    body = str(text or "").strip().lower()
    if not body:
        return False
    return any(word.lower() in body for word in words)


def detect_human_request(query: str) -> bool:
    """买家是否明确要人工（词表见 settings.HANDOFF_HUMAN_KEYWORDS）。"""
    return _hit_keywords(query, _words(settings.HANDOFF_HUMAN_KEYWORDS))


def detect_negative_sentiment(query: str) -> bool:
    """买家是否情绪激烈：愤怒词表命中，或出现连续感叹号强调。"""
    if _hit_keywords(query, _words(settings.HANDOFF_ANGRY_KEYWORDS)):
        return True
    body = str(query or "")
    return "!!" in body or "！！" in body


def streak(guards: list[dict[str, Any]], flag: str) -> int:
    """从最新（列表首位）往前数连续命中 flag 的轮次。

    口径：坐席人工代回（guard.by == "agent"）即清零——人工已介入，不再累计「连续不懂」。
    """
    count = 0
    for guard in guards:
        if not isinstance(guard, dict):
            break
        if str(guard.get("by") or "") == "agent":
            break
        if bool(guard.get(flag)):
            count += 1
            continue
        break
    return count


def _missed(guard: Any) -> bool:
    """该轮是否算「未解决」（拒答 或 工具空手），用于「连续不懂」计数。"""
    if not isinstance(guard, dict):
        return False
    return bool(guard.get("rejected")) or bool(guard.get("empty"))


def missed_streak(guards: list[dict[str, Any]]) -> int:
    """连续未解决轮次（rejected / empty 两标记任一为真即计一轮）。"""
    count = 0
    for guard in guards:
        if not isinstance(guard, dict):
            break
        if str(guard.get("by") or "") == "agent":
            break
        if _missed(guard):
            count += 1
            continue
        break
    return count


def blank_decision(enabled: bool = True) -> dict[str, Any]:
    """「本轮没有命中的规则」的规整返回：未命中 / 规则表关闭 / 重放不重判三种情形共用一份形状。"""
    return {
        "hit": False,
        "enabled": enabled,
        "code": "",
        "label": "",
        "reason": "",
        "priority": 0,
        "matched": [],
        "matched_rules": [],
    }


def evaluate(signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """按规则表判定本轮是否该转人工（纯函数，不改任何状态）。

    signals 由调用方组，认识这些键：
      query（买家原话，用于喊人工/情绪判定）、explicit_request、negative_sentiment、
      approval_pending、vision_need_human、no_evidence、agent_no_result、tool_empty、
      miss_streak / degrade_streak（连续计数，由 workbench_service 查历史 guard 得到）。
    """
    data = dict(signals or {})
    if not settings.HANDOFF_ENABLED:
        return blank_decision(enabled=False)

    query = str(data.get("query") or "")
    if query:
        if detect_human_request(query):
            data.setdefault("explicit_request", True)
        if detect_negative_sentiment(query):
            data.setdefault("negative_sentiment", True)

    matched: list[dict[str, Any]] = []
    for rule in RULES:
        if rule.threshold_field:
            threshold = int(getattr(settings, rule.threshold_field, 0) or 0)
            count = int(data.get(rule.signal) or 0)
            if threshold <= 0 or count < threshold:
                continue
            detail = rule.reason.format(n=count)
        else:
            if not bool(data.get(rule.signal)):
                continue
            detail = rule.reason
        matched.append(
            {"code": rule.code, "label": rule.label, "reason": detail, "priority": rule.priority}
        )

    if not matched:
        return blank_decision(enabled=True)

    top = matched[0]
    result = blank_decision(enabled=True)
    result.update(
        {
            "hit": True,
            "code": top["code"],
            "label": top["label"],
            "reason": top["reason"],
            "priority": top["priority"],
        }
    )
    result["matched"] = [item["code"] for item in matched]
    result["matched_rules"] = matched
    return result


def rule_table() -> list[dict[str, Any]]:
    """规则清单（GET /workbench/handoff-rules 的唯一口径）：含当前阈值与是否生效。"""
    enabled_all = bool(settings.HANDOFF_ENABLED)
    rows: list[dict[str, Any]] = []
    for rule in RULES:
        threshold = 0
        if rule.threshold_field:
            threshold = int(getattr(settings, rule.threshold_field, 0) or 0)
        rows.append(
            {
                "code": rule.code,
                "label": rule.label,
                "reason": rule.reason,
                "priority": rule.priority,
                "signal": rule.signal,
                "threshold": threshold,
                "enabled": enabled_all and (not rule.threshold_field or threshold > 0),
            }
        )
    return rows
