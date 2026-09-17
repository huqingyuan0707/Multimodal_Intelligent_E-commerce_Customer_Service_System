"""规则机器人单测（FR-5 三级容错第三级：网关类故障切确定性兜底，对齐 FRDv2 FR-5）

链路：纯函数（触发判定/状态行/组装）→ 编排层失败收集（4007 快失败不断言 executor 行为本身）
     → 对话链降级分支（模型挂了走规则组装而非静态模板）→ run 路径注记（态仍 FAILED）。
覆盖红线：触发集合只含网关码（业务拒绝/权限/参数不触发）；正文引用编号不越界；
         空依据回落静态模板（与今日行为一致）；转人工信号不受影响。
运行（backend/ 目录）：pytest tests/test_rulebot.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.core.exceptions import BusinessError, ErrorCode
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.session import init_models
from app.main import app
from app.modules.agent import connectors, executor, runtime
from app.modules.agent.contracts import ToolContext
from app.services import chat_service, llm_service, rulebot_service

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])

_current = {"user": TESTER}


async def _override() -> CurrentUser:
    """可切换鉴权（本文件固定 tester，租户隔离用例另行代入）。"""
    set_current_user(_current["user"])
    return _current["user"]


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI 真调客户端（独立临时库；连接器注册与 test_agent_runtime 同口径）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'rulebot.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    connectors.register_all()
    executor.reset_breakers()
    set_current_user(TESTER)
    app.dependency_overrides[get_current_user] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    executor.reset_breakers()


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """直连会话（编排/run 级用例与 client 共享 tmp 库文件）。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'rulebot.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    connectors.register_all()
    executor.reset_breakers()
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import get_engine

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session
    executor.reset_breakers()


def _refs() -> list[dict[str, object]]:
    return [
        {"title": "退货政策", "content": "支持七天无理由退货，质量问题十五天。"},
        {"title": "发货时效", "content": "48 小时内发出，偏远地区顺延。"},
    ]


# ---------------- 纯函数：触发判定 ----------------


def test_gateway_trigger_only_covers_gateway_codes() -> None:
    """触发集合：4007 熔断/4002 超时/4008 上游失败才触发；业务拒绝与权限参数不触发。"""
    assert rulebot_service.is_gateway_failure(ErrorCode.TOOL_CIRCUIT_OPEN) is True
    assert rulebot_service.is_gateway_failure(4007) is True
    assert rulebot_service.is_gateway_failure(ErrorCode.TASK_TIMEOUT) is True
    assert rulebot_service.is_gateway_failure(ErrorCode.TOOL_CALL_FAILED) is True
    assert rulebot_service.is_gateway_failure(ErrorCode.TOOL_SCOPE_DENIED) is False
    assert rulebot_service.is_gateway_failure(ErrorCode.PARAM_INVALID) is False
    assert rulebot_service.is_gateway_failure(ErrorCode.ORDER_NOT_FOUND) is False
    assert rulebot_service.is_gateway_failure(ErrorCode.NO_EVIDENCE) is False
    assert rulebot_service.is_gateway_failure(None) is False
    assert rulebot_service.is_gateway_failure("熔断") is False


def test_status_line_per_tool_and_code() -> None:
    """状态行：已知工具中文名 + 故障原因词；未知工具回落原文名；非网关码空串。"""
    line = rulebot_service.status_line("logistics.query", ErrorCode.TOOL_CIRCUIT_OPEN)
    assert "物流查询" in line and "熔断" in line and "转人工" in line
    assert "响应超时" in rulebot_service.status_line("order.query", 4002)
    assert "上游服务异常" in rulebot_service.status_line("stock.query", 4008)
    assert "ghost.tool" in rulebot_service.status_line("ghost.tool", 4007)
    assert rulebot_service.status_line("order.query", 4006) == ""
    assert rulebot_service.status_block([]) == ""
    block = rulebot_service.status_block(
        [
            {"tool": "logistics.query", "code": 4007, "message": "x"},
            {"tool": "logistics.query", "code": 4007, "message": "y"},
            {"tool": "order.query", "code": 1001, "message": "z"},
        ]
    )
    assert "物流查询" in block and "order.query" not in block, "同工具去重，非网关码不进块"


# ---------------- 纯函数：确定性组装 ----------------


def test_compose_uses_verified_data_only() -> None:
    """组装：KB 摘要 + 业务事实 + 服务状态 + 明示 footer；引用编号不越界。"""
    out = rulebot_service.compose(
        refs=_refs(),
        tool_block="订单 TB-1 当前为「待发货」。",
        failures=[{"tool": "logistics.query", "code": 4007, "message": "open"}],
    )
    assert out["engaged"] is True
    text = str(out["text"])
    assert "知识库原文摘要" in text  # 存量降级断言口径保持
    assert "订单 TB-1" in text  # 已验证的业务事实原样复述
    assert "物流查询" in text and "熔断" in text  # 失败状态确定性说明
    assert "未经过模型生成" in text and "转人工" in text  # 降级明示 + 人工入口保留
    assert set(out["rules_hit"]) == {"biz_facts", "kb_digest", "service_status"}
    import re

    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
    assert cited <= {1, 2}, "引用编号不得越界（faithfulness 不扣分）"


def test_compose_empty_falls_back_to_template() -> None:
    """无 refs/事实/网关失败：engaged=False，调用方回落静态模板（今日行为不变）。"""
    out = rulebot_service.compose(refs=[])
    assert out == {"text": "", "rules_hit": [], "engaged": False}
    text, engaged = rulebot_service.answer_or_fallback("退货吗", refs=_refs())
    assert engaged is True and "知识库原文摘要" in text
    plain, engaged_plain = rulebot_service.answer_or_fallback("退货吗", refs=[])
    assert engaged_plain is False and "知识库原文摘要" in plain


# ---------------- 编排层：失败收集 ----------------


async def test_orchestrate_circuit_failure_marks_rulebot(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """编排步遇 4007：rejected 照常记录 + rulebot 置位 + 状态块点名故障工具。"""
    set_current_user(TESTER)

    async def _open(_ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        raise BusinessError(ErrorCode.TOOL_CIRCUIT_OPEN, "工具 kb.retrieve 连续失败已熔断", 503)

    monkeypatch.setattr(executor, "call", _open)
    data = await runtime.orchestrate(db, user=TESTER, query="退货政策是什么")
    assert data["rulebot"] is True
    assert "知识库检索" in str(data["rulebot_block"])
    assert "熔断" in str(data["rulebot_block"])
    assert any("规则机器人" in note for note in data["notes"])
    assert data["tool_calls"] and data["tool_calls"][0]["status"] == "rejected"
    assert data["tool_calls"][0]["code"] == int(ErrorCode.TOOL_CIRCUIT_OPEN)


async def test_orchestrate_business_rejection_not_rulebot(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """业务拒绝（非网关码）：rejected 照常，但不触发规则机器人。"""
    set_current_user(TESTER)

    async def _reject(_ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        raise BusinessError(ErrorCode.ORDER_NOT_FOUND, "订单不存在", 404)

    monkeypatch.setattr(executor, "call", _reject)
    data = await runtime.orchestrate(db, user=TESTER, query="退货政策是什么")
    assert data["rulebot"] is False
    assert data["rulebot_block"] == ""


# ---------------- 对话链：降级分支 ----------------


async def test_answer_uses_rulebot_when_llm_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型挂了：规则机器人组装（含 KB 摘要原文短语）+ degraded + model=template + rulebot 透出。"""
    set_current_user(CurrentUser(username="tester", tenant=TENANT, roles=["cs"]))

    async def _down(*a: object, **k: object) -> Any:
        raise llm_service.LlmUnavailableError("ollama down")

    monkeypatch.setattr(llm_service, "complete", _down)
    result = await chat_service.answer("退货政策是什么")
    assert result["degraded"] is True
    assert result["model"] == "template"
    assert result.get("rulebot") is True
    assert "知识库原文摘要" in str(result["answer"])
    assert "未经过模型生成" in str(result["answer"])


# ---------------- run 路径：注记但态不变 ----------------


async def test_drive_gateway_failure_notes_rulebot(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run 路径遇网关故障：任务态仍 FAILED（诚实收敛），但 notes 留下规则机器人兜底说明。"""
    set_current_user(TESTER)

    async def _open(_ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        raise BusinessError(ErrorCode.TOOL_CIRCUIT_OPEN, "工具 kb.retrieve 连续失败已熔断", 503)

    monkeypatch.setattr(executor, "call", _open)
    data = await runtime.run(db, user=TESTER, query="退货政策是什么")
    assert data["state"] == "FAILED"
    assert any("规则机器人" in note for note in data["notes"])
