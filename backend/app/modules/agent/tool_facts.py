"""工具结果中文事实（编排内核的结果展示层，对齐 FRDv2 FR-3 + 附录 A）

职责：把连接器返回的真实结构翻成「一句话中文事实」，并判定「空手而归」。
链路：executor.call 得到 result → summarize() 拼 facts → tool_block 以【业务查询】
      块注入 chat_prompt.build_messages（不占 [n] 引用编号）；is_empty() 为空则
      在 runtime 侧转人工（对齐 2001 无据拒答口径，绝不拿空结果硬答）。

红线：只复述工具真实返回，不加戏、不编造物流节点与时效；纯函数，不碰 DB、不调模型。
本模块从 runtime.py 拆出（该文件受行数预算棘轮约束），函数体逐字未改。
"""

from __future__ import annotations

from typing import Any


def _yuan(cents: Any) -> str:
    """分转元展示（金额一律整数分存储，展示层才转元）。"""
    try:
        return f"{(int(cents) / 100):.2f} 元"
    except (TypeError, ValueError):
        return "未知金额"


def is_empty(tool: str, result: dict[str, Any]) -> bool:
    """结果是否「空手而归」：空手即转人工，绝不拿空结果硬答。"""
    if tool == "kb.retrieve":
        return int(result.get("total", 0)) == 0
    if tool == "coupon.query":
        return int(result.get("total", 0)) == 0
    if tool == "stock.query":
        return int(result.get("warehouse_count", 0)) == 0
    return False


def summarize(tool: str, args: dict[str, Any], result: dict[str, Any]) -> str:
    """把工具真实返回翻成中文一句话（只复述，不加戏、不编造节点与时效）。"""
    if tool == "order.query":
        return (
            f"订单 {result.get('outer_id', '')} 当前为「{result.get('status_label', '')}」，"
            f"金额 {_yuan(result.get('total'))}。"
        )
    if tool == "logistics.query":
        return (
            f"物流单号 {result.get('tracking_no', '')}（{result.get('company', '')}）"
            f"当前状态「{result.get('status_label', '')}」，轨迹节点对接后补齐。"
        )
    if tool == "stock.query":
        size = str(result.get("size", "") or "").strip() or "全部尺码"
        return f"{size} 可用库存 {result.get('available', 0)} 件。"
    if tool == "coupon.query":
        return f"当前有 {result.get('total', 0)} 个进行中的优惠活动。"
    if tool == "kb.retrieve":
        refs = result.get("references") or []
        if not refs:
            return "知识库未检索到权威依据，已转人工确认。"
        titles = "、".join(str(ref.get("title", "")) for ref in refs[:3])
        return f"已检索到 {result.get('total', 0)} 条政策依据：{titles}。"
    if tool == "refund.create":
        return (
            f"已提交退款申请（金额 {_yuan(args.get('amount'))}），"
            f"进入审批后由人工确认，账目暂未变动。"
        )
    return f"工具 {tool} 执行完成。"
