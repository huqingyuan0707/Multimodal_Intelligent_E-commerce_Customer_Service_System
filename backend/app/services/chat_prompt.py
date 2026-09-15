"""问答提示词组装（RAG 生成段拼装层，对齐 RAG 规范 §4 + FR-1.4）

链路：chat_service.answer → build_messages（资料预算 + 图像检测 + 历史对话）
      → llm_service.complete；降级走 fallback_answer；引用校验 validate_references。
纯函数为主，可单测；阈值/预算全走 Settings，禁止字面量。
"""

from __future__ import annotations

import re

from app.config import settings

# 提示词硬约束：宁可不答不可答错（换模型不改这里）
_SYSTEM_PROMPT = (
    "你是电商店铺的在线客服，代表商家回答买家问题。必须遵守："
    "1) 只依据【资料】与【业务查询】作答，两者都没有的价格、尺码、面料、发货时限、快递单号、政策一律不得编造；"
    "2) 资料不足以回答时，直接说明「这点资料里没有，我帮你转人工确认」，不要猜测；"
    "3) 用简体中文，简洁分点，引用来源时在句末标注编号，例如 [1]。"
)

_CITED = re.compile(r"\[(\d{1,2})\]")


def build_messages(
    query: str,
    refs: list[dict[str, object]],
    vision_block: str = "",
    history_block: str = "",
    tool_block: str = "",
) -> list[dict[str, str]]:
    """拼提示词：资料按 [n] 编号注入（单条 LLM_REF_CHARS 截断，总预算 TOP_K 倍封顶）。

    拼接预算：总资料字符超 TOP_K*LLM_REF_CHARS 则从末尾丢块，保证小模型上下文不爆。
    图文轮 vision_block（检测结果）插在资料与问题之间，LLM 按“致歉+定级+方案+时效”生成。
    多轮 history_block（摘要 + 窗口，context_service 已做预算裁剪/PII 清洗）插在检测后。
    tool_block 为 Agent 编排（FR-3/FR-5 接线）实查到的业务事实（订单/物流/库存等）：
    与【资料】并列作为可依据事实，但不参与 [n] 编号，避免 LLM 编造出不存在的引用号。
    """
    budget = settings.TOP_K * settings.LLM_REF_CHARS
    blocks: list[str] = []
    used = 0
    for i, ref in enumerate(refs, 1):
        piece = str(ref.get("content", ""))[: settings.LLM_REF_CHARS]
        if used + len(piece) > budget:
            break
        used += len(piece)
        blocks.append(f"[{i}]《{ref.get('title', '')}》{piece}")
    body = "\n".join(blocks)
    vision = f"\n\n【图像检测】\n{vision_block[:800]}" if vision_block.strip() else ""
    tool = f"\n\n【业务查询】\n{tool_block[:800]}" if tool_block.strip() else ""
    history = (
        f"\n\n{history_block[: settings.SESSION_TOKEN_BUDGET * 2]}" if history_block.strip() else ""
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"【资料】\n{body}{tool}{vision}{history}\n\n【问题】{query[:500]}\n"
                "请只依据上面资料与业务查询结果作答，历史对话仅用于理解指代（如“这个”“刚才那件”）。"
            ),
        },
    ]


def fallback_answer(
    query: str,
    refs: list[dict[str, object]],
    vision_block: str = "",
    history_block: str = "",
) -> str:
    """降级回复（模型不可用时）：检测结论 + 资料摘要，不编造引用之外的单号与政策。"""
    lines = ["已为你找到相关的店内政策（以下为知识库原文摘要）："]
    if vision_block.strip():
        lines.append(f"【图像检测】\n{vision_block[:400]}")
    if history_block.strip():
        lines.append(f"{history_block[:400]}")
    for i, ref in enumerate(refs, 1):
        lines.append(f"[{i}]《{ref.get('title', '')}》：{str(ref.get('content', ''))[:120]}")
    lines.append("如需人工跟进，可直接回复“转人工”。")
    _ = query
    return "\n".join(lines)


def faithfulness(text: str, ref_count: int) -> float:
    """忠实度：答案自报的引用编号必须都落在实际资料范围内，越界按比例扣分（疑似编造）。"""
    cited = {int(num) for num in _CITED.findall(text)}
    if not cited:
        return 0.9
    valid = set(range(1, ref_count + 1))
    return round(len(cited & valid) / len(cited), 2)


def validate_references(text: str, refs: list[dict[str, object]]) -> dict[str, object]:
    """引用校验（第 11 步）：faithfulness + 越界编号 + guard 判定（纯函数可单测）。

    guard.pass=False 当 faith < FAITHFULNESS_WARN 或出现越界引用；调用方据此进 Mining。
    """
    faith = faithfulness(text, len(refs))
    cited = sorted({int(n) for n in _CITED.findall(text or "")})
    bad = [n for n in cited if n < 1 or n > len(refs)]
    passed = faith >= settings.FAITHFULNESS_WARN and not bad
    return {"faithfulness": faith, "cited": cited, "bad": bad, "guard": {"pass": passed}}
