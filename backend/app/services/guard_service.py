"""输入域守卫（问答第一道闸门，对齐 FRDv2 §安全/FR-5 规则机器人 + 测试评估验收方案 §6）

链路：chat_service._assemble_generation 检索前 → check(query) →
      injection（提示词注入/越权诱导）或 off_domain（电商客服域外闲聊）→ 直接抛
      NoEvidenceError 转人工；其余放行给 RAG 检索与生成。
红线：纯函数（不碰 DB/模型），词表与正则一律读 Settings（可热更），禁止散落硬编码；
      只拦「确定域外/确定注入」，拿不准一律放行给 RAG 治理兜底——误拦比漏拦更伤体验。
口径：FRD 验收（幻觉 ≤2%）需要「守卫 + rerank 精排 + judge」叠加；本模块是 P0 第一层，
      黄金集 eval_golden.py 同口径统计各层拦了多少（guard/retrieval 两路归因）。
"""

from __future__ import annotations

import re
from typing import Any

from app.config import settings

_CACHE: dict[str, Any] = {"stamp": "", "injection": [], "off": ()}


def _compiled() -> tuple[list[re.Pattern[str]], tuple[str, ...]]:
    """词表惰性编译（Settings 热更后自动重建，双检靠 stamp 比对，纯读无锁风险）。"""
    stamp = f"{settings.GUARD_INJECTION_PATTERNS}|{settings.GUARD_OFF_DOMAIN_KEYWORDS}"
    if _CACHE["stamp"] != stamp:
        _CACHE["injection"] = [
            re.compile(p, re.IGNORECASE) for p in settings.GUARD_INJECTION_PATTERNS
        ]
        _CACHE["off"] = tuple(w.lower() for w in settings.GUARD_OFF_DOMAIN_KEYWORDS if w)
        _CACHE["stamp"] = stamp
    return _CACHE["injection"], _CACHE["off"]


def detect_injection(query: str) -> str:
    """注入/越权诱导判定：命中模式原文返回（坐席可读），无命中返回空串。"""
    body = str(query or "").strip()
    if not body:
        return ""
    for pattern in _compiled()[0]:
        if pattern.search(body):
            return pattern.pattern
    return ""


def detect_off_domain(query: str) -> bool:
    """域外判定：黑名单命中即域外。词表只收「与电商客服无歧义」的闲聊/套话词
    （天气/股票/代码…），不做「必须含业务词」的反向兜底——买家口语千变万化，
    反向兜底误伤真实咨询；域内无据由 RAG 检索阈值负责拒答，两闸各司其职。
    """
    body = str(query or "").strip().lower()
    if not body:
        return True
    return any(word in body for word in _compiled()[1])


def check(query: str) -> dict[str, Any]:
    """守卫主入口：返回 {refuse, category, reason}；拒绝话术必须中文可操作。

    category: injection（诱导越权/套提示词）/ off_domain（与电商客服无关）/ 空=放行。
    开关 GUARD_ENABLED=false 时整体旁路（回滚位，与 AGENT_CHAT_ORCHESTRATE 同款）。
    """
    if not settings.GUARD_ENABLED:
        return {"refuse": False, "category": "", "reason": ""}
    hit = detect_injection(query)
    if hit:
        return {
            "refuse": True,
            "category": "injection",
            "reason": "这类请求涉及越权或内部信息，需要人工客服核实处理",
        }
    if detect_off_domain(query):
        return {
            "refuse": True,
            "category": "off_domain",
            "reason": "这个问题超出了本店客服范围，我帮你转人工确认",
        }
    return {"refuse": False, "category": "", "reason": ""}
