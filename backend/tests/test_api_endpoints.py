"""端点集成测试（全路由 Happy Path + 错误信封，对齐 API 规范 §4/§7 联调门禁）

链路：httpx ASGITransport → app（含 TraceMiddleware 与 BusinessError→fail 映射）
      → endpoints 薄封装 → services（临时 SQLite 库 + 种子数据）。
口径：
- 鉴权依赖整体替换为通配 tester（roles=["*"]），只验端点装配与出参形状，不重复验鉴权逻辑。
- 不触发 lifespan，建表与种子由夹具完成；llm 只走空 query 与 probe 降级分支，不连真实模型。
运行（backend/ 目录）：pytest tests/test_api_endpoints.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app

TENANT = settings.SEED_TENANT
TESTER = CurrentUser(username="tester", tenant=TENANT, roles=["*"])


async def _tester_override() -> CurrentUser:
    """鉴权替换：通配权限 + 写入 ContextVar（service 经 current_user() 取人不断）。"""
    set_current_user(TESTER)
    return TESTER


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 全量种子 + 鉴权替换的 ASGI 客户端。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    await init_models()
    assert await seed_on_startup() is True
    app.dependency_overrides[get_current_user] = _tester_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _ok(resp: httpx.Response) -> dict:
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


async def test_api_happy_paths_cover_endpoints(client: httpx.AsyncClient) -> None:
    """全路由走一遍：断言信封 ok + 关键字段，为覆盖率补端点/中间件/RBAC 行。"""
    # 认证：真实登录 + 失败分支 + me/logout（替换鉴权）
    data = (
        await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    ).json()
    assert data["code"] == 0 and data["data"]["token"]
    bad = (
        await client.post("/api/v1/auth/login", json={"username": "admin", "password": "错"})
    ).json()
    assert bad["code"] == 1002
    empty = (await client.post("/api/v1/auth/login", json={"username": "", "password": ""})).json()
    assert empty["code"] == 1001
    me = await _ok(await client.get("/api/v1/auth/me"))
    assert me["name"] == "tester"
    await _ok(await client.post("/api/v1/auth/logout"))
    # 代入切换：通配 tester 切种子 admin 成功（审计同事务提交），幽灵用户 404
    sw = await _ok(await client.post("/api/v1/auth/switch", json={"username": "admin"}))
    assert sw["user"]["name"] == "admin" and sw["token"]
    ghost = await client.post("/api/v1/auth/switch", json={"username": "ghost"})
    assert ghost.json()["code"] == 1004

    # 会话：真实落库（空 body 建默认标题；列表空/有数据均 200；未知 id 404 回 mock）
    created = await _ok(await client.post("/api/v1/sessions"))
    assert created["id"]
    await _ok(await client.get("/api/v1/sessions"))
    detail = await _ok(await client.get(f"/api/v1/sessions/{created['id']}"))
    assert detail["id"] == created["id"] and detail["messages"] == []
    missing = await client.get("/api/v1/sessions/abc")
    assert missing.status_code == 404 and missing.json()["code"] == 1004
    await _ok(await client.delete(f"/api/v1/sessions/{created['id']}"))
    gone = await client.delete(f"/api/v1/sessions/{created['id']}")
    assert gone.status_code == 404 and gone.json()["code"] == 1004
    await _ok(await client.get("/api/v1/documents"))
    nofile = (await client.post("/api/v1/documents/upload")).json()
    assert nofile["code"] == 1001
    up = await _ok(
        await client.post("/api/v1/documents/upload", files={"file": ("a.txt", b"hello")})
    )
    assert "doc_id" in up
    await _ok(await client.post("/api/v1/documents/reindex"))
    task = await _ok(await client.post("/api/v1/tasks", json={"type": "demo"}))
    await _ok(await client.get(f"/api/v1/tasks/{task['task_id'] or 't1'}"))

    # 对话：空 query 走 1001/空流 done 帧，不连真实模型
    assert (await client.post("/api/v1/chat", json={"query": "  "})).json()["code"] == 1001
    stream = await client.post("/api/v1/chat/stream", json={"query": ""})
    assert stream.status_code == 200 and "done" in stream.text
    # 规范路径别名同样可达（任务 + FRDv2 口径）
    agent_stream = await client.post("/api/v1/agent/chat/stream", json={"query": ""})
    assert agent_stream.status_code == 200 and "done" in agent_stream.text

    # 治理巡检（无模型走降级分支，不断）
    gov = await _ok(await client.get("/api/v1/governance/status"))
    assert "llm" in gov

    # 商品：列表取 SKU → 改价进审批 → 行内编辑 → 上下架（变更均回 kb_doc，FR-10.1）
    goods = await _ok(await client.get("/api/v1/goods"))
    assert goods["total"] == 2
    sku_id = goods["items"][0]["skus"][0]["id"]
    approval = await _ok(
        await client.post(
            f"/api/v1/goods/skus/{sku_id}/price-change",
            json={"new_price": 9900, "reason": "覆盖率巡检"},
        )
    )
    assert approval["status"] == "pending"
    edited = await _ok(
        await client.put(f"/api/v1/goods/skus/{sku_id}", json={"barcode": "690000001"})
    )
    assert "kb_doc" in edited and edited["kb_doc"]["title"].startswith("商品知识｜")
    changed = await _ok(
        await client.put(f"/api/v1/goods/{goods['items'][0]['id']}/status", json={"status": "off"})
    )
    assert "kb_doc" in changed and changed["kb_doc"]["title"].startswith("商品知识｜")

    # 审批：批种子单 + 驳改价单
    pending = await _ok(await client.get("/api/v1/approvals", params={"status": "pending"}))
    assert len(pending) >= 2
    first, second = pending[0]["id"], pending[1]["id"]
    assert (await _ok(await client.post(f"/api/v1/approvals/{first}/approve", json={})))[
        "status"
    ] == "approved"
    rejected = await _ok(
        await client.post(f"/api/v1/approvals/{second}/reject", json={"reason": "覆盖率巡检驳回"})
    )
    assert rejected["status"] == "rejected"

    # 库存：查表/仓库/流水 → 入库 → 调拨 → 盘点无差异 → 补货进审批
    stock = await _ok(await client.get("/api/v1/inventory", params={"size": 200}))
    row = stock["items"][0]
    houses = await _ok(await client.get("/api/v1/inventory/warehouses"))
    assert len(houses) == 2
    await _ok(await client.get("/api/v1/inventory/moves", params={"sku_id": row["sku_id"]}))
    await _ok(
        await client.post(
            "/api/v1/inventory/moves",
            json={
                "kind": "in",
                "warehouse_id": row["warehouse_id"],
                "sku_id": row["sku_id"],
                "delta": 1,
                "reason": "巡检",
            },
        )
    )
    other = next(w["id"] for w in houses if w["id"] != row["warehouse_id"])
    await _ok(
        await client.post(
            "/api/v1/inventory/moves",
            json={
                "kind": "move",
                "warehouse_id": row["warehouse_id"],
                "to_warehouse_id": other,
                "sku_id": row["sku_id"],
                "delta": 1,
                "reason": "巡检调拨",
            },
        )
    )
    checked = await _ok(
        await client.post(
            "/api/v1/inventory/stocktake",
            json={
                "lines": [
                    {
                        "warehouse_id": row["warehouse_id"],
                        "sku_id": row["sku_id"],
                        "counted": row["qty"] + 1,
                    }
                ],
                "reason": "巡检盘点",
            },
        )
    )
    assert checked["checked"] == 1
    await _ok(
        await client.post(
            "/api/v1/inventory/replenish",
            json={"sku_id": row["sku_id"], "qty": 5, "reason": "巡检补货"},
        )
    )

    # 订单履约 + 售后证据链
    orders = await _ok(await client.get("/api/v1/orders"))
    paid = next(o for o in orders["items"] if o["status"] == "paid")
    shipped = await _ok(
        await client.post(
            f"/api/v1/orders/{paid['id']}/ship",
            json={"company": "顺丰", "tracking_no": "SF1000000001"},
        )
    )
    assert shipped["logistics_status"] == "created"
    detail = await _ok(await client.get(f"/api/v1/orders/{paid['id']}"))
    assert detail["trace_id"] is not None
    after = await _ok(
        await client.post(
            "/api/v1/aftersales",
            json={
                "order_id": paid["id"],
                "reason": "巡检",
                "amount": 100,
                "trace_id": "t-api",
                "evidence": ["https://cdn/x.jpg"],
            },
        )
    )
    assert after["need_approval"] is False
    listed = await _ok(await client.get("/api/v1/aftersales"))
    # v0.3.21 售后列表已切服务端分页：data 为 {total,page,size,items}
    assert any(a["evidence"] == ["https://cdn/x.jpg"] for a in listed["items"])

    # 物流：公司表 → 单号查询 → 异常转售后
    companies = await _ok(await client.get("/api/v1/logistics/companies"))
    assert len(companies) == 8
    tracked = await _ok(
        await client.post("/api/v1/logistics/track", json={"tracking_no": "SF1234567890"})
    )
    assert tracked["status_label"]
    abnormal = await _ok(
        await client.post(
            "/api/v1/logistics/exceptions", json={"logistics_id": tracked["id"], "kind": "stuck"}
        )
    )
    assert abnormal["aftersale_id"]

    # 评价工单流：入库 → 回复 → 建单 → 转交 → 关闭
    review = await _ok(
        await client.post(
            "/api/v1/reviews",
            json={"platform": "淘宝", "outer_id": "TB-1", "level": "bad", "content": "差"},
        )
    )
    await _ok(await client.get("/api/v1/reviews", params={"level": "bad"}))
    await _ok(await client.post(f"/api/v1/reviews/{review['id']}/reply", json={"reply": "抱歉"}))
    created = await _ok(await client.post(f"/api/v1/reviews/{review['id']}/ticket", json={}))
    ticket_id = created["ticket"]["id"]
    await _ok(await client.get("/api/v1/tickets"))
    await _ok(await client.post(f"/api/v1/tickets/{ticket_id}/transfer", json={"assignee": "ops"}))
    await _ok(
        await client.post(f"/api/v1/tickets/{ticket_id}/close", json={"conclusion": "已回访"})
    )

    # 营销：建活动带有效期 → 发券幂等回放 → 会员查调分
    promo = await _ok(
        await client.post(
            "/api/v1/promos",
            json={
                "name": "巡检活动",
                "budget": 5,
                "valid_from": "2026-09-01 00:00:00",
                "valid_to": "2026-09-30 23:59:59",
            },
        )
    )
    assert promo["valid_from"] and promo["remaining"] == 5
    promos = await _ok(await client.get("/api/v1/promos"))
    assert any(p["id"] == promo["id"] for p in promos)
    first_grant = await _ok(
        await client.post(
            f"/api/v1/promos/{promo['id']}/grant",
            json={"user_ref": "u-api"},
            headers={"Idempotency-Key": "api-cov-1"},
        )
    )
    replay = await _ok(
        await client.post(
            f"/api/v1/promos/{promo['id']}/grant",
            json={"user_ref": "u-api"},
            headers={"Idempotency-Key": "api-cov-1"},
        )
    )
    assert replay["id"] == first_grant["id"]
    member = await _ok(await client.get("/api/v1/members/u-api"))
    assert member["points"] == 0
    await _ok(await client.post("/api/v1/members/u-api/points", json={"delta": 1200}))


async def test_api_error_paths_map_to_fail_envelope(client: httpx.AsyncClient) -> None:
    """错误分支进统一 fail 信封（号段不断，HTTP 状态与业务码同行）。"""
    cases = [
        ("get", "/api/v1/orders/nope", None, 404, 3001),
        (
            "post",
            "/api/v1/inventory/moves",
            {"kind": "bogus", "warehouse_id": "w", "sku_id": "s", "delta": 1, "reason": "x"},
            400,
            1001,
        ),
        ("post", "/api/v1/inventory/stocktake", {"lines": [], "reason": "x"}, 400, 1001),
        ("post", "/api/v1/approvals/nope/approve", {}, 404, 1004),
        # 评价/物流/发券的 NOT_FOUND 沿用 BusinessError 默认 HTTP 400，信封码 1004 为准
        ("post", "/api/v1/reviews/nope/reply", {"reply": "x"}, 400, 1004),
        ("post", "/api/v1/logistics/track", {"tracking_no": "NOTEXIST00"}, 400, 1004),
        ("post", "/api/v1/promos/none/grant", {"user_ref": "u"}, 400, 1004),
    ]
    for method, path, payload, http_status, code in cases:
        resp = await client.request(method, path, json=payload, headers={"Idempotency-Key": "e1"})
        assert resp.status_code == http_status, (path, resp.text[:200])
        assert resp.json()["code"] == code, (path, resp.text[:200])

    # 状态机拒绝：已发货订单不可再发货/售后只能在可售后状态建
    shipped_list = await _ok(await client.get("/api/v1/orders", params={"status": "shipped"}))
    resp = await client.post(
        f"/api/v1/orders/{shipped_list['items'][0]['id']}/ship",
        json={"company": "顺丰", "tracking_no": "SF1000000002"},
    )
    assert resp.json()["code"] == 3005
    pending_list = await _ok(await client.get("/api/v1/orders", params={"status": "pending_pay"}))
    resp = await client.post(
        "/api/v1/aftersales",
        json={
            "order_id": pending_list["items"][0]["id"],
            "reason": "x",
            "amount": 0,
            "trace_id": "",
        },
    )
    assert resp.json()["code"] == 3005

    # 重复审批拒绝 + 无幂等键发券拒绝 + 空结论关单拒绝
    pending = await _ok(await client.get("/api/v1/approvals", params={"status": "pending"}))
    await _ok(await client.post(f"/api/v1/approvals/{pending[0]['id']}/approve", json={}))
    again = await client.post(f"/api/v1/approvals/{pending[0]['id']}/approve", json={})
    assert again.json()["code"] == 4004
    promo = await _ok(await client.post("/api/v1/promos", json={"name": "p2", "budget": 1}))
    nokey = await client.post(f"/api/v1/promos/{promo['id']}/grant", json={"user_ref": "u"})
    assert nokey.json()["code"] == 1001
    review = await _ok(await client.post("/api/v1/reviews", json={"level": "bad", "content": "c"}))
    ticket = await _ok(await client.post(f"/api/v1/reviews/{review['id']}/ticket", json={}))
    noclose = await client.post(
        f"/api/v1/tickets/{ticket['ticket']['id']}/close", json={"conclusion": " "}
    )
    assert noclose.json()["code"] == 1001

    # 无权限进 403（HTTPException 原生体，非信封）
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="nobody", tenant=TENANT, roles=[]
    )
    resp = await client.get("/api/v1/approvals")
    assert resp.status_code == 403
    # 非 admin 代入被拦 403/1003（无 admin Scope，审计不落）
    resp = await client.post("/api/v1/auth/switch", json={"username": "admin"})
    assert resp.status_code == 403 and resp.json()["code"] == 1003
