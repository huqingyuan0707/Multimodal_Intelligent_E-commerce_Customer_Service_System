"""页面闭环演示种子（会话/消息/工具调用/成本/审计/质检评分）

链路：app.db.seed.ensure_closed_loop_demo() → _seed_sessions() / _seed_ops_records()
     （由 seed.py 编排；_rel() 供 seed_biz_records 复用）。
对齐数据模型与存储设计.md §6 迁移节；由 B2B_SEED_DEMO 控制、已存在会话即跳过。
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    AuditLog,
    CostRecord,
    Message,
    Session,
    SessionScore,
    ToolCall,
)

# ==================== 闭环演示数据（每个页面都有真数据，无前端 mock） ====================
# 设计口径（对齐执行步骤「数据闭环」）：
# - 一次灌齐 sessions/messages/tool_calls/cost_records/audit_logs/aftersales/eval_runs/
#   promos+grants+members/reviews/tickets/session_scores + 回溯订单 + cs 坐席账号，
#   让聊天、工作台、看板、大屏、商品、库存、订单、售后、审批、知识库、Studio、Admin
#   全部渲染真实 DB 数据（前端不再有 @/mock 兜底）。
# - 时间一律相对「灌种时刻」回推：订单铺满近 7 日喂 GMV 趋势，消息铺满今日小时桶喂看板趋势，
#   另有「近 5 分钟」消息让 QPS 非 0；绝不写死绝对日期（否则换天跑就没有趋势）。
# - 幂等判据：本租户 sessions 已有数据即整体跳过（B2B_SEED_DEMO=false 时同样跳过）。

_DEMO_AGENTS: tuple[tuple[str, str, str], ...] = (
    # (用户名, roles, 说明)：cs:<组> 令牌即技能组（handoff_rules.agent_skills 唯一口径）
    ("liuwei", "cs,cs:refund,cs:aftersale,order:read,order:fulfill", "退款/售后专席"),
    ("chenyu", "cs,cs:aftersale,cs:complaint,order:read,order:fulfill", "售后/投诉专席"),
)

_CITATIONS = [
    {
        "source": "policy-3.2",
        "title": "售后政策第 3.2 条｜7 天无理由与质量问题 15 天",
        "score": 0.92,
    },
    {"source": "flow-exchange", "title": "换货处理流程｜质检与二次入库", "score": 0.87},
]
_SIZING_CITATIONS = [
    {"source": "size-guide", "title": "尺码指南｜常规版按平时码，修身版大一码", "score": 0.9},
    {"source": "product-TSIRT-001", "title": "商品知识｜重磅纯棉短袖 T 恤", "score": 0.85},
]


@dataclass(frozen=True)
class _DemoSessionSpec:
    """演示会话：owner 决定归属（admin=登录账号的聊天历史；买家名=工作台队列买家）。

    turns 为 (role, content) 序列，agent 行由落库逻辑统一补引用/trace/成本。
    """

    owner: str
    title: str
    status: str
    skill: str
    assignee: str
    reason: str
    summary: str
    resolution: str
    hours_ago: float
    turns: tuple[tuple[str, str], ...]
    citations: tuple[dict[str, object], ...] = ()


_DEMO_SESSIONS: tuple[_DemoSessionSpec, ...] = (
    # 三条挂在登录账号名下：对话页左侧历史/工作台「AI 接待」筛选都有真实数据
    _DemoSessionSpec(
        owner="",
        title="卫衣 M 码还有货吗",
        status="none",
        skill="general",
        assignee="",
        reason="",
        summary="买家咨询加绒连帽卫衣 M 码库存与发货时效，AI 已按商品知识与尺码指南答复。",
        resolution="",
        hours_ago=0.03,
        turns=(
            ("user", "加绒连帽卫衣 M 码还有货吗？"),
            (
                "agent",
                "您好，加绒连帽卫衣（米白/咖啡）M 码中心仓与华东仓均有现货，"
                "下单后 48 小时内发出；建议按平时穿着尺码下单，喜欢宽松可选大一码。",
            ),
            ("user", "好的，那米白 M 码我拍一件。"),
            ("agent", "已为您记录，米白 M 码售价 299 元。付款后可在「我的订单」查看物流。"),
        ),
        citations=tuple(_SIZING_CITATIONS),
    ),
    _DemoSessionSpec(
        owner="",
        title="七天无理由退货怎么算时间",
        status="none",
        skill="general",
        assignee="",
        reason="",
        summary="买家咨询退货起算时间与运费承担，AI 依据售后政策第 3.2 条答复。",
        resolution="",
        hours_ago=5.0,
        turns=(
            ("user", "七天无理由是从下单算还是签收算？"),
            (
                "agent",
                "7 天无理由自「签收当日」起算，非质量问题退货运费由买家承担；"
                "质量问题 15 天内可退换，运费由我们承担。",
            ),
        ),
        citations=tuple(_CITATIONS),
    ),
    _DemoSessionSpec(
        owner="",
        title="T 恤洗后掉色怎么处理",
        status="none",
        skill="general",
        assignee="",
        reason="",
        summary="买家反馈重磅纯棉 T 恤首次水洗掉色，AI 给出洗涤口径与换货路径。",
        resolution="",
        hours_ago=26.0,
        turns=(
            ("user", "这件 T 恤第一次洗就掉色了，正常吗？"),
            (
                "agent",
                "重磅纯棉深色款首次水洗有轻微浮色属正常，建议机洗 30℃、不可漂白、阴凉处晾干。"
                "若大面积掉色影响穿着，可在订单内申请质量问题换货，15 天内运费由我们承担。",
            ),
            ("user", "那我申请换一件黑色的。"),
        ),
        citations=tuple(_CITATIONS),
    ),
    # 五条买家名的会话：喂工作台待接队列/技能组筛选/负载与绩效
    _DemoSessionSpec(
        owner="王女士",
        title="卫衣买大了一码想退货",
        status="pending",
        skill="refund",
        assignee="",
        reason="买家明确要求退货退款，命中退款技能组",
        summary="买家尺码偏大申请退货，等待退款专席接单。",
        resolution="",
        hours_ago=0.6,
        turns=(
            ("user", "卫衣买大了，能退吗？"),
            ("agent", "可以。签收后 7 天内支持无理由退货，我为您转接退款专席处理。"),
            ("user", "好，我要转人工。"),
        ),
        citations=tuple(_CITATIONS),
    ),
    _DemoSessionSpec(
        owner="李先生",
        title="收到衣服袖口脱线",
        status="pending",
        skill="aftersale",
        assignee="",
        reason="质量问题需人工质检判定，命中售后技能组",
        summary="袖口脱线申请换货，待售后专席判定处置方式。",
        resolution="",
        hours_ago=1.8,
        turns=(
            ("user", "袖口这里脱线了，我拍了图。"),
            (
                "agent",
                "已收到您的图片。袖口脱线属质量问题，15 天内可换货；"
                "需要人工质检确认处置方式，正在为您转接售后专席。",
            ),
        ),
        citations=tuple(_CITATIONS),
    ),
    _DemoSessionSpec(
        owner="张女士",
        title="物流三天没更新要投诉",
        status="handling",
        skill="complaint",
        assignee="chenyu",
        reason="买家情绪激烈提及投诉，命中投诉技能组",
        summary="买家因物流停滞表达不满，已由投诉专席接手跟进。",
        resolution="",
        hours_ago=3.5,
        turns=(
            ("user", "快递三天没动了，再这样我就投诉！"),
            ("agent", "非常抱歉给您带来困扰，已记录您的问题，马上为您转接投诉专席。"),
            ("user", "我等你们回复。"),
        ),
        citations=tuple(_CITATIONS),
    ),
    _DemoSessionSpec(
        owner="陈先生",
        title="换货进度到哪一步了",
        status="handling",
        skill="aftersale",
        assignee="liuwei",
        reason="买家追问换货单进度，命中售后技能组",
        summary="换货已寄出，坐席跟进回寄与二次入库进度。",
        resolution="",
        hours_ago=9.0,
        turns=(
            ("user", "我上周寄回的换货，什么时候发出新的？"),
            (
                "agent",
                "已查到您的换货单，回寄件已签收，质检通过后 24 小时内发出新品，"
                "现在为您转接售后专席跟进。",
            ),
            ("user", "好的谢谢。"),
        ),
        citations=tuple(_CITATIONS),
    ),
    _DemoSessionSpec(
        owner="赵女士",
        title="退款到账时间确认",
        status="resolved",
        skill="refund",
        assignee="liuwei",
        reason="退款到账时效咨询，命中退款技能组",
        summary="买家确认退款到账时间，坐席已答复并归档。",
        resolution="已答复：原路退回 1-3 个工作日到账，买家确认无异议。",
        hours_ago=30.0,
        turns=(
            ("user", "退款什么时候能到账？"),
            ("agent", "退款原路退回，一般 1-3 个工作日到账，已为您发起。"),
            ("user", "好的，已经收到了。"),
        ),
        citations=tuple(_CITATIONS),
    ),
)

_DEMO_AUDITS: tuple[tuple[str, str, str, str], ...] = (
    ("tenant.create", settings.SEED_TENANT, '{"plan": "trial"}', "演示租户开户"),
    (
        "user.create",
        settings.SEED_USERNAME,
        '{"roles": "cs,kb,shop,stock,ops,admin"}',
        "种子账号创建",
    ),
    ("tenant.quota", settings.SEED_TENANT, '{"quota_tokens": 1000000}', "配额调整"),
    ("user.roles", "liuwei", '{"roles": "cs,cs:refund,cs:aftersale"}', "开通退款/售后技能组"),
    ("user.roles", "chenyu", '{"roles": "cs,cs:aftersale,cs:complaint"}', "开通售后/投诉技能组"),
    ("apikey.create", "ops-portal", '{"mask": "sk_live_****a1b2"}', "开放平台密钥创建"),
)


def _rel(hours_ago: float) -> datetime:
    """相对灌种时刻回推（禁用绝对日期，换天跑也有趋势）。"""
    return datetime.now() - timedelta(hours=hours_ago)


async def _seed_sessions(db: AsyncSession, *, tenant: str, username: str) -> list[Session]:
    """会话 + 消息：admin 名下 3 条（对话页历史）+ 买家名 5 条（工作台队列）。"""
    created: list[Session] = []
    for index, spec in enumerate(_DEMO_SESSIONS):
        owner = spec.owner or username
        created_at = _rel(spec.hours_ago)
        row = Session(
            tenant=tenant,
            username=owner,
            title=spec.title,
            summary=spec.summary,
            handoff_status=spec.status,
            assignee=spec.assignee,
            handoff_reason=spec.reason,
            handoff_skill=spec.skill,
            resolution=spec.resolution,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(row)
        await db.flush()
        created.append(row)
        trace_id = f"trace{index + 1:02d}{zlib.crc32(spec.title.encode()) % 10**6:06d}"
        for turn_index, (role, content) in enumerate(spec.turns):
            # 首条 user 消息落在「近 5 分钟」内，保证看板 QPS 非 0 且今日小时桶有柱
            stamp = (
                _rel(0.05)
                if (index == 0 and turn_index == 0)
                else created_at + timedelta(minutes=turn_index * 2)
            )
            if role == "agent":
                db.add(
                    Message(
                        session_id=row.id,
                        tenant=tenant,
                        role="agent",
                        modality="text",
                        content=content,
                        citations=json.dumps(list(spec.citations), ensure_ascii=False),
                        guard=json.dumps({"pass": True, "by": "rag"}, ensure_ascii=False),
                        faithfulness=0.94,
                        trace_id=trace_id,
                        client_msg_id=f"seed-{row.id}-{turn_index}",
                        cost_cents=12 + turn_index * 3,
                        created_at=stamp,
                    )
                )
            else:
                db.add(
                    Message(
                        session_id=row.id,
                        tenant=tenant,
                        role="user",
                        modality="text",
                        content=content,
                        client_msg_id=f"seed-{row.id}-{turn_index}",
                        created_at=stamp,
                    )
                )
        await db.flush()
    return created


async def _seed_ops_records(
    db: AsyncSession, *, tenant: str, username: str, sessions_results: list[Session]
) -> None:
    """工具调用/成本/审计/质检评分：喂看板慢 Trace、成本卡、Admin 审计、坐席绩效。"""
    trace_ids = [f"trace{i + 1:02d}" for i in range(len(sessions_results))]
    for index, latency in enumerate((8640, 6120, 4380, 2960, 1840, 1220)):
        db.add(
            ToolCall(
                trace_id=trace_ids[index % len(trace_ids)],
                tenant=tenant,
                username=username,
                name=("order.query", "stock.query", "kb.retrieve", "coupon.query")[index % 4],
                args="{}",
                result=json.dumps({"ok": True}, ensure_ascii=False),
                latency_ms=latency,
                created_at=_rel(1.0 + index * 2),
            )
        )
    for index in range(8):
        db.add(
            CostRecord(
                tenant=tenant,
                session_id=sessions_results[index % len(sessions_results)].id,
                model=settings.LLM_MODEL,
                prompt_tokens=620 + index * 40,
                completion_tokens=180 + index * 15,
                cost_cents=8 + index,
                pricing_source="estimate" if index % 3 == 0 else "usage",
                created_at=_rel(2.0 + index * 3),
            )
        )
    for action, target, detail, note in _DEMO_AUDITS:
        db.add(
            AuditLog(
                tenant=tenant,
                actor=username,
                action=action,
                target=target,
                detail=json.dumps({"note": note, **json.loads(detail)}, ensure_ascii=False),
                created_at=_rel(48.0),
            )
        )
    # 质检评分：只给已解决的会话落分（绩效面板口径：resolved 且 assignee 非空才计入）
    for row in sessions_results:
        if row.handoff_status != "resolved" or not row.assignee:
            continue
        db.add(
            SessionScore(
                tenant=tenant,
                session_id=row.id,
                assignee=row.assignee,
                score=5,
                resolution_ok=1,
                source="judge",
                reviewer="",
                detail=json.dumps({"note": "回答有据、结论明确", "by": "seed"}, ensure_ascii=False),
            )
        )
    await db.flush()
