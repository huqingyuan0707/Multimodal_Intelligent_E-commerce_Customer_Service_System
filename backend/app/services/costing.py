"""成本折算单实现（LLM token→分 + 人工基线对照，对齐 FRD §1 降本增效）

链路：chat_turn_store._record_cost_and_audit → price_llm_turn → CostRecord.cost_cents
      (+pricing_source) 与 messages.cost_cents 双写；看板/评估读同一口径。
口径：单价全在 Settings（LLM_COST_PER_1K_TOKENS 元/千 tokens，可热更）；
上游 usage 有数用实数（source=usage），否则用 estimate_tokens 估算（source=estimate，
中文 1.5 字/token，与预算裁剪同源）；人工单通基线 HUMAN_COST_PER_TICKET_CENTS
默认 ¥15（生产按财务口径覆盖），归因误差度量 = 估算单占比（越低越准）。
"""

from __future__ import annotations

from app.config import settings


def price_llm_turn(prompt_tokens: int, completion_tokens: int) -> int:
    """LLM 一轮费用（分）：(prompt+comp)/1000 × 单价(元/千) × 100，四舍五入。"""
    total = max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0))
    return round(total / 1000 * float(settings.LLM_COST_PER_1K_TOKENS) * 100)


def vs_human_ratio(cost_cents: float) -> float | None:
    """单会话成本 ≈ 人工基线百分之几（基线未配≤0 时回 None 不编数）。"""
    base = int(settings.HUMAN_COST_PER_TICKET_CENTS)
    if base <= 0:
        return None
    return round(float(cost_cents) / base * 100, 1)
