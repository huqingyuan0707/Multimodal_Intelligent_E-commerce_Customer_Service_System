"""规则机器人（FR-5 三级容错第三级：网关类故障时的数据驱动确定性兜底）

三级容错定位（FRDv2 FR-5：重试 → 预设话术 → 网关熔断切规则机器人）：
- L1 重试：executor 对幂等工具退避重试（已落地）；
- L2 预设话术：chat_prompt.fallback_answer 静态 KB 摘要（已落地）；
- L3 规则机器人（本模块）：失败属于网关类（模型不可用 / 工具熔断 4007 /
  超时 4002 / 上游失败 4008）时，用已验证的数据（检索引用 + 编排已成功的
  业务事实 + 失败工具状态）按确定性规则组装回复，而非静态模板。

红线（与 L2 的本质区别仍是同一条：绝不编造）：
- 只复述 refs/facts 里已存在的内容；未知的一律明示"暂不可用 + 已排队 + 转人工"；
- 正文不写 [n] 引用编号（只复用 refs 摘要行的原编号），引用校验不扣分；
- 触发即记 trace + observability（agent.rulebot），转人工照常触发——
  规则机器人替代的是"哑模板"，不是人工。
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ErrorCode
from app.services.chat_prompt import _plain_text

# 网关类故障码：触发规则机器人的失败集合（业务拒绝/权限/参数不在此列，
# 它们走原有分支，保持"正常拒绝不当故障"的口径）。
GATEWAY_CODES: frozenset[int] = frozenset(
    {
        int(ErrorCode.TOOL_CIRCUIT_OPEN),  # 4007 熔断开闸
        int(ErrorCode.TASK_TIMEOUT),  # 4002 工具超时
        int(ErrorCode.TOOL_CALL_FAILED),  # 4008 上游依赖失败
    }
)

# 失败原因中文词（状态行用；与 executor 的 4002/4008 区分口径一致）
_CODE_WORDS: dict[int, str] = {
    int(ErrorCode.TOOL_CIRCUIT_OPEN): "熔断保护中",
    int(ErrorCode.TASK_TIMEOUT): "响应超时",
    int(ErrorCode.TOOL_CALL_FAILED): "上游服务异常",
}

# 工具中文名（状态行用；注册中心 6 连接器全覆盖，未知工具回落原文名）
_TOOL_WORDS: dict[str, str] = {
    "order.query": "订单查询",
    "logistics.query": "物流查询",
    "stock.query": "库存查询",
    "coupon.query": "优惠查询",
    "kb.retrieve": "知识库检索",
    "refund.create": "退款申请",
}

_RULEBOT_HEADER = "【规则兜底回复】模型服务暂不可用，以下依据已查到的数据整理（未经过模型生成）："
_RULEBOT_FOOTER = "如需人工跟进，可直接回复“转人工”。"
_KB_DIGEST_HEADER = "已为你找到相关的店内政策（以下为知识库原文摘要）："


def is_gateway_failure(code: object) -> bool:
    """是否为网关类故障（触发规则机器人；其余一律走原分支）。"""
    try:
        return int(code) in GATEWAY_CODES  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return False


def tool_word(tool: str) -> str:
    """工具中文名（未知工具回落原文名，不编造新名）。"""
    return _TOOL_WORDS.get(str(tool or ""), str(tool or "未知工具"))


def status_line(tool: str, code: object) -> str:
    """单工具网关故障状态行（确定性话术：状态 + 已排队 + 转人工指引）。

    非网关码返回 ""（调用方只把网关失败喂进来，此处再守一道）。
    """
    try:
        code_int = int(code)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return ""
    if code_int not in GATEWAY_CODES:
        return ""
    word = _CODE_WORDS[code_int]
    return f"{tool_word(tool)}服务暂不可用（{word}），已为你排队，转人工可优先跟进。"


def status_block(failures: list[dict[str, Any]]) -> str:
    """失败集合转规则状态块（按工具去重，供提示词 verified 上下文与兜底正文复用）。"""
    lines: list[str] = []
    seen: set[str] = set()
    for item in failures or []:
        tool = str(item.get("tool", ""))
        if not tool or tool in seen:
            continue
        line = status_line(tool, item.get("code"))
        if line:
            seen.add(tool)
            lines.append(f"- {line}")
    if not lines:
        return ""
    return "【服务状态】\n" + "\n".join(lines)


def compose(
    *,
    refs: list[dict[str, object]],
    tool_block: str = "",
    failures: list[dict[str, Any]] | None = None,
    vision_block: str = "",
) -> dict[str, Any]:
    """确定性组装规则兜底回复（纯函数）：refs 摘要 + 业务事实 + 服务状态 + 明示 footer。

    返回 {"text", "rules_hit", "engaged"}：engaged 为 False 时调用方回落
    fallback_answer（与今日行为完全一致）；rules_hit 供可观测与单测断言。
    正文引用编号只来自 refs 摘要行（ faithfulness 不扣分）。
    """
    refs = [r for r in refs or [] if isinstance(r, dict)]
    facts = (tool_block or "").strip()
    block = status_block(list(failures or []))
    vision = (vision_block or "").strip()
    rules_hit: list[str] = []
    if not refs and not facts and not block:
        return {"text": "", "rules_hit": rules_hit, "engaged": False}
    lines = [_RULEBOT_HEADER]
    if vision:
        lines.append(f"【图像检测】\n{vision[:400]}")
        rules_hit.append("vision")
    if facts:
        lines.append(f"【已查到的业务信息】\n{facts[:800]}")
        rules_hit.append("biz_facts")
    if refs:
        lines.append(_KB_DIGEST_HEADER)
        for i, ref in enumerate(refs, 1):
            summary = _plain_text(str(ref.get("content", "")))[:120]
            lines.append(f"[{i}]《{ref.get('title', '')}》：{summary}")
        rules_hit.append("kb_digest")
    if block:
        lines.append(block)
        rules_hit.append("service_status")
    lines.append(_RULEBOT_FOOTER)
    return {"text": "\n".join(lines), "rules_hit": rules_hit, "engaged": True}


def answer_or_fallback(
    query: str,
    *,
    refs: list[dict[str, object]],
    tool_block: str = "",
    failures: list[dict[str, Any]] | None = None,
    vision_block: str = "",
) -> tuple[str, bool]:
    """规则机器人优先，组装不出（无 refs/事实/网关失败）则回落静态模板。

    返回 (正文, 是否命中规则机器人)。两个分支都不抛异常、不调模型。
    """
    from app.services.chat_prompt import fallback_answer

    composed = compose(
        refs=refs, tool_block=tool_block, failures=failures, vision_block=vision_block
    )
    if composed["engaged"]:
        return str(composed["text"]), True
    return fallback_answer(query, refs, vision_block), False
