"""管理后台扩展功能集成测试（密钥/SLO/消息模板/排班，对齐 FRD FR-8/FR-12.2/FR-12.4）

链路：ASGI 真调（临时库 + 种子 + 可切换鉴权）→ 密钥全生命周期（创建回明文一次 →
      列表只回掩码 → 轮换换掩码 → 禁用/启用 → 审计留痕）→ 越权与租户过滤断言。
运行（backend/ 目录）：pytest tests/test_admin_ops.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.core import cache, observability
from app.core.rbac import get_current_user
from app.core.user_context import CurrentUser, set_current_user
from app.db import session as session_mod
from app.db.seed import seed_on_startup
from app.db.session import init_models
from app.main import app

TENANT = settings.SEED_TENANT
ADMIN = CurrentUser(username="admin", tenant=TENANT, roles=["*"])
CS_ONLY = CurrentUser(username="cs1", tenant=TENANT, roles=["cs"])

_current: dict[str, CurrentUser] = {"user": ADMIN}


async def _override() -> CurrentUser:
    """可切换鉴权：按用例在 admin / 普通客服之间代入（ContextVar 同步写）。"""
    set_current_user(_current["user"])
    return _current["user"]


def login_as(user: CurrentUser) -> None:
    _current["user"] = user


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """独立临时库 + 全量种子 + 可切换鉴权 ASGI 客户端。"""
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'adminops.db'}")
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_SessionFactory", None)
    # 测试不写可观测 JSONL（避免把探针产物落进仓库），内存计数照常可用
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)
    await init_models()
    assert await seed_on_startup() is True
    login_as(ADMIN)
    app.dependency_overrides[get_current_user] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


async def _create_key(
    client: httpx.AsyncClient, name: str = "订单同步", **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tenant": TENANT, "name": name, "scopes": "order:read"}
    payload.update(extra)
    return await _ok(await client.post("/api/v1/admin/api-keys", json=payload))


# ==================== 密钥管理（FR-8「密钥（只显掩码）」） ====================


async def test_create_key_returns_plaintext_once(client: httpx.AsyncClient) -> None:
    """建密钥回明文一次（形态正确），列表结构上不含明文与摘要。"""
    data = await _create_key(client)
    plain = data["plaintext"]
    assert plain.startswith(f"{settings.API_KEY_PREFIX}_")
    assert len(plain) > len(settings.API_KEY_PREFIX) + 20
    assert data["item"]["status"] == "active"

    listed = await _ok(await client.get("/api/v1/admin/api-keys", params={"tenant": TENANT}))
    assert listed["total"] == 1
    item = listed["items"][0]
    assert "plaintext" not in item
    assert "key_hash" not in item
    assert plain not in str(item)


async def test_list_never_exposes_secret(client: httpx.AsyncClient) -> None:
    """列表只回掩码：前缀保留、正文中间打码、首尾各留 MASK_KEEP 位。"""
    data = await _create_key(client, name="库存同步")
    plain = data["plaintext"]
    masked = data["item"]["masked"]
    keep = int(settings.API_KEY_MASK_KEEP)
    assert masked.startswith(f"{settings.API_KEY_PREFIX}_")
    assert "****" in masked
    assert plain not in masked
    assert masked.endswith(plain[-keep:])
    assert data["item"]["scopes"] == ["order:read"]


async def test_duplicate_name_rejected(client: httpx.AsyncClient) -> None:
    """同租户同名密钥拒绝（1001，中文可操作提示）。"""
    await _create_key(client, name="重复名")
    resp = await client.post(
        "/api/v1/admin/api-keys",
        json={"tenant": TENANT, "name": "重复名", "scopes": ""},
    )
    body = resp.json()
    assert body["code"] == 1001
    assert "同名" in body["msg"]


async def test_rotate_changes_mask_and_revives(client: httpx.AsyncClient) -> None:
    """轮换：掩码变化 + rotated_at 落值 + 状态复位启用（旧口令失效由摘要覆盖保证）。"""
    created = await _create_key(client)
    key_id = created["item"]["id"]
    await _ok(
        await client.post(f"/api/v1/admin/api-keys/{key_id}/status", json={"status": "disabled"})
    )
    rotated = await _ok(await client.post(f"/api/v1/admin/api-keys/{key_id}/rotate"))
    assert rotated["plaintext"] != created["plaintext"]
    assert rotated["item"]["rotated_at"] != ""
    assert rotated["item"]["status"] == "active"
    assert rotated["item"]["masked"] != created["item"]["masked"]


async def test_status_switch_and_invalid_value(client: httpx.AsyncClient) -> None:
    """禁用/启用可用；非法状态 1001。"""
    created = await _create_key(client)
    key_id = created["item"]["id"]
    disabled = await _ok(
        await client.post(f"/api/v1/admin/api-keys/{key_id}/status", json={"status": "disabled"})
    )
    assert disabled["status_label"] == "已禁用"
    enabled = await _ok(
        await client.post(f"/api/v1/admin/api-keys/{key_id}/status", json={"status": "active"})
    )
    assert enabled["status_label"] == "启用"

    bad = await client.post(f"/api/v1/admin/api-keys/{key_id}/status", json={"status": "gone"})
    assert bad.json()["code"] == 1001


async def test_bad_expires_at_rejected(client: httpx.AsyncClient) -> None:
    """到期时间格式非法 1001；合法格式落库并回显。"""
    bad = await client.post(
        "/api/v1/admin/api-keys",
        json={"tenant": TENANT, "name": "坏时间", "expires_at": "2026/09/17"},
    )
    assert bad.json()["code"] == 1001

    ok_row = await _create_key(client, name="到期密钥", expires_at="2026-12-31")
    assert ok_row["item"]["expires_at"].startswith("2026-12-31")
    assert ok_row["item"]["expired"] is False


async def test_audits_recorded(client: httpx.AsyncClient) -> None:
    """创建/轮换/状态变更各留一条审计（谁/何时/干什么），detail 只含掩码。"""
    created = await _create_key(client, name="审计密钥")
    key_id = created["item"]["id"]
    await _ok(await client.post(f"/api/v1/admin/api-keys/{key_id}/rotate"))
    await _ok(
        await client.post(f"/api/v1/admin/api-keys/{key_id}/status", json={"status": "disabled"})
    )
    audits = await _ok(
        await client.get("/api/v1/admin/audits", params={"keyword": "审计密钥", "size": 20})
    )
    actions = {item["action"] for item in audits["items"]}
    assert {"apikey.create", "apikey.rotate", "apikey.status"} <= actions
    for item in audits["items"]:
        assert "plaintext" not in str(item["detail"])


async def test_non_admin_forbidden(client: httpx.AsyncClient) -> None:
    """非 admin 角色访问密钥面直接 403（不泄漏存在性）。"""
    login_as(CS_ONLY)
    resp = await client.get("/api/v1/admin/api-keys")
    assert resp.status_code == 403


async def test_tenant_filter_and_missing_key(client: httpx.AsyncClient) -> None:
    """租户过滤生效；不存在的密钥 1004。"""
    await _create_key(client, name="本租户")
    other = await _ok(
        await client.get("/api/v1/admin/api-keys", params={"tenant": "no-such-tenant"})
    )
    assert other["total"] == 0
    assert other["size"] == 20

    missing = await client.post("/api/v1/admin/api-keys/not-exist/rotate")
    assert missing.json()["code"] == 1004


# ==================== SLO 告警（FR-8「SLO 告警」） ====================


async def _upsert_rule(client: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant": TENANT,
        "metric": "reject_count",
        "operator": "lte",
        "threshold": 10,
    }
    payload.update(extra)
    return await _ok(await client.post("/api/v1/admin/slo/rules", json=payload))


async def test_slo_metrics_catalog_marks_scope(client: httpx.AsyncClient) -> None:
    """指标目录与实时值同源；值来源层级如实标注为 process。"""
    data = await _ok(await client.get("/api/v1/admin/slo/metrics"))
    metrics = {item["metric"] for item in data["items"]}
    assert {"handoff_answer_rate", "answer_p95_seconds", "llm_ok_rate", "tool_ok_rate"} <= metrics
    assert data["metric_scope"] == "process"
    assert "进程级" in data["scope_note"]


async def test_no_data_not_faked_as_zero(client: httpx.AsyncClient) -> None:
    """从没测过的比率指标回 no_data + current=None，绝不拿 0 冒充。"""
    observability.reset()
    row = await _upsert_rule(client, metric="handoff_answer_rate", operator="gte", threshold=0.95)
    assert row["current"] is None
    assert row["no_data"] is True
    assert row["breach"] is False


async def test_breach_detected_from_real_counter(client: httpx.AsyncClient) -> None:
    """计数类指标按真事件计数当场判定（不 mock 业务逻辑，直接投递可观测事件）。"""
    observability.reset()
    observability.record("chat.reject", {"tenant": TENANT})
    row = await _upsert_rule(client, metric="reject_count", operator="lte", threshold=0)
    assert row["current"] == 1.0
    assert row["no_data"] is False
    assert row["breach"] is True
    observability.reset()


async def test_disabled_rule_never_breaches(client: httpx.AsyncClient) -> None:
    """停用规则不参与超标判定（避免误读成正在告警）。"""
    observability.reset()
    observability.record("chat.reject", {"tenant": TENANT})
    row = await _upsert_rule(client, operator="lte", threshold=0, enabled=False)
    assert row["current"] == 1.0
    assert row["breach"] is False
    observability.reset()


async def test_upsert_overwrites_single_rule(client: httpx.AsyncClient) -> None:
    """同租户同指标只留一条：二次提交即改口径，不产生重复规则。"""
    first = await _upsert_rule(client, threshold=10)
    second = await _upsert_rule(client, threshold=3)
    assert first["id"] == second["id"]
    assert second["threshold"] == 3.0
    listed = await _ok(await client.get("/api/v1/admin/slo/rules", params={"tenant": TENANT}))
    assert listed["total"] == 1
    assert listed["size"] == 20


async def test_invalid_metric_operator_window_rejected(client: httpx.AsyncClient) -> None:
    """指标/方向/窗口任一非法都回 1001（窗口只有 realtime，today 需历史报表故拒收）。"""
    bad_metric = await client.post(
        "/api/v1/admin/slo/rules",
        json={"tenant": TENANT, "metric": "no_such", "threshold": 1},
    )
    assert bad_metric.json()["code"] == 1001

    bad_op = await client.post(
        "/api/v1/admin/slo/rules",
        json={"tenant": TENANT, "metric": "reject_count", "operator": "eq", "threshold": 1},
    )
    assert bad_op.json()["code"] == 1001

    bad_window = await client.post(
        "/api/v1/admin/slo/rules",
        json={"tenant": TENANT, "metric": "reject_count", "threshold": 1, "window": "today"},
    )
    assert bad_window.json()["code"] == 1001
    assert "realtime" in bad_window.json()["msg"]


async def test_toggle_and_delete_rule(client: httpx.AsyncClient) -> None:
    """启停可用；删除后列表清空且落审计；重复删除 1004。"""
    created = await _upsert_rule(client)
    rule_id = created["id"]
    off = await _ok(
        await client.post(f"/api/v1/admin/slo/rules/{rule_id}/enabled", json={"enabled": False})
    )
    assert off["enabled"] is False
    on = await _ok(
        await client.post(f"/api/v1/admin/slo/rules/{rule_id}/enabled", json={"enabled": True})
    )
    assert on["enabled"] is True

    await _ok(await client.delete(f"/api/v1/admin/slo/rules/{rule_id}"))
    listed = await _ok(await client.get("/api/v1/admin/slo/rules", params={"tenant": TENANT}))
    assert listed["total"] == 0
    again = await client.delete(f"/api/v1/admin/slo/rules/{rule_id}")
    assert again.json()["code"] == 1004

    audits = await _ok(await client.get("/api/v1/admin/audits", params={"keyword": "reject_count"}))
    assert any(item["action"] == "slo.delete" for item in audits["items"])


# ==================== 消息模板与频控（FR-12.2） ====================


async def _create_tpl(client: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant": TENANT,
        "name": "发货通知",
        "channel": "sms",
        "content": "亲，您的订单已发货：{user_ref}",
        "status": "draft",
    }
    payload.update(extra)
    return await _ok(await client.post("/api/v1/admin/notify/templates", json=payload))


async def test_template_create_and_list(client: httpx.AsyncClient) -> None:
    """建模板（draft）→ 列表可见；渠道非法 1001；渠道清单与后端同源。"""
    created = await _create_tpl(client)
    assert created["status_label"] == "草稿"
    assert created["no_data"] is True  # 从未发送过 → 到达率无数据，而非 0
    listed = await _ok(
        await client.get("/api/v1/admin/notify/templates", params={"tenant": TENANT})
    )
    assert listed["total"] == 1
    assert listed["size"] == 20
    assert listed["channels"] == ["sms", "wechat", "dingtalk", "email"]
    assert "累计口径" in listed["window_note"]

    bad = await client.get("/api/v1/admin/notify/templates", params={"channel": "fax"})
    assert bad.json()["code"] == 1001


async def test_template_duplicate_name_and_empty_body(client: httpx.AsyncClient) -> None:
    """同名 1001；正文为空的模板不允许启用（否则会发空消息出去）。"""
    await _create_tpl(client, name="重复模板")
    again = await client.post(
        "/api/v1/admin/notify/templates",
        json={"tenant": TENANT, "name": "重复模板", "content": "x"},
    )
    assert again.json()["code"] == 1001

    empty = await _create_tpl(client, name="空模板", content="")
    resp = await client.post(
        f"/api/v1/admin/notify/templates/{empty['id']}/status", json={"status": "active"}
    )
    assert resp.json()["code"] == 1001
    assert "正文为空" in resp.json()["msg"]


async def test_send_requires_active_template(client: httpx.AsyncClient) -> None:
    """未启用模板不能发送（1001）。"""
    await _create_tpl(client, name="未启用")
    resp = await client.post(
        "/api/v1/admin/notify/send",
        json={"tenant": TENANT, "name": "未启用", "user_ref": "buyer-1"},
    )
    assert resp.json()["code"] == 1001

    missing = await client.post(
        "/api/v1/admin/notify/send",
        json={"tenant": TENANT, "name": "根本不存在", "user_ref": "buyer-1"},
    )
    assert missing.json()["code"] == 1004


async def test_send_reports_not_delivered_honestly(client: httpx.AsyncClient) -> None:
    """网关未接入：如实回 delivered=false + degraded=true，并记账为未送达（不冒充成功）。"""
    created = await _create_tpl(client, name="到货提醒", status="active")
    sent = await _ok(
        await client.post(
            "/api/v1/admin/notify/send",
            json={"tenant": TENANT, "name": "到货提醒", "user_ref": "buyer-1"},
        )
    )
    assert sent["delivered"] is False
    assert sent["degraded"] is True
    assert "网关未接入" in sent["reason"]
    assert "buyer-1" in sent["content"]  # {user_ref} 已渲染

    listed = await _ok(
        await client.get("/api/v1/admin/notify/templates", params={"tenant": TENANT})
    )
    item = next(row for row in listed["items"] if row["id"] == created["id"])
    assert item["sent"] == 1
    assert item["failed"] == 1
    assert item["reach_rate"] == 0.0  # 真发不出去就显示 0，不做「假成功」


async def test_rate_limit_blocks_second_send(client: httpx.AsyncClient) -> None:
    """频控（默认同一接收方 24h 内最多 1 条）：第二次 1006 + HTTP 429。"""
    cache.reset()
    await _create_tpl(client, name="限流模板", status="active")
    await _ok(
        await client.post(
            "/api/v1/admin/notify/send",
            json={"tenant": TENANT, "name": "限流模板", "user_ref": "buyer-lim"},
        )
    )
    blocked = await client.post(
        "/api/v1/admin/notify/send",
        json={"tenant": TENANT, "name": "限流模板", "user_ref": "buyer-lim"},
    )
    assert blocked.json()["code"] == 1006
    assert blocked.status_code == 429

    # 换个接收方不受影响（频控按接收方计数，不按模板全局计数）
    await _ok(
        await client.post(
            "/api/v1/admin/notify/send",
            json={"tenant": TENANT, "name": "限流模板", "user_ref": "buyer-other"},
        )
    )
    cache.reset()


async def test_reach_report_no_data_then_real_zero(client: httpx.AsyncClient) -> None:
    """到达率报表：无发送 no_data；发送后如实显示 0%（不是假 100%）。"""
    await _create_tpl(client, name="报表模板", status="active")
    before = await _ok(await client.get("/api/v1/admin/notify/reach", params={"tenant": TENANT}))
    assert before["no_data"] is True
    assert before["reach_rate"] is None
    assert "累计口径" in before["window_note"]

    await _ok(
        await client.post(
            "/api/v1/admin/notify/send",
            json={"tenant": TENANT, "name": "报表模板", "user_ref": "buyer-3"},
        )
    )
    after = await _ok(await client.get("/api/v1/admin/notify/reach", params={"tenant": TENANT}))
    assert after["total_sent"] == 1
    assert after["reach_rate"] == 0.0


async def test_delete_template(client: httpx.AsyncClient) -> None:
    created = await _create_tpl(client, name="待删模板")
    await _ok(await client.delete(f"/api/v1/admin/notify/templates/{created['id']}"))
    listed = await _ok(
        await client.get("/api/v1/admin/notify/templates", params={"tenant": TENANT})
    )
    assert listed["total"] == 0
    again = await client.delete(f"/api/v1/admin/notify/templates/{created['id']}")
    assert again.json()["code"] == 1004


# ==================== 组织：排班 / 绩效 / 离职冻结（FR-12.4） ====================


async def _seed_user(username: str, roles: str = "cs") -> str:
    """直插一个用户行：seed 只建 admin，而排班/冻结断言需要真实用户。"""
    from app.core.security import hash_password
    from app.db.models import User

    async for db in session_mod.get_db():
        row = User(
            tenant=TENANT,
            username=username,
            roles=roles,
            pwd_hash=hash_password("pw-123456"),
        )
        db.add(row)
        await db.commit()
        return str(row.id)
    return ""


async def test_shift_create_list_delete(client: httpx.AsyncClient) -> None:
    """排班登记/列表/删除；技能组清单与队列路由同源。"""
    await _seed_user("cs-shift")
    created = await _ok(
        await client.post(
            "/api/v1/admin/org/shifts",
            json={
                "tenant": TENANT,
                "username": "cs-shift",
                "work_date": "2026-09-20",
                "start_time": "09:00",
                "end_time": "18:00",
                "skill": "refund",
            },
        )
    )
    assert created["skill_label"] == "退款售后"
    listed = await _ok(
        await client.get(
            "/api/v1/admin/org/shifts", params={"tenant": TENANT, "work_date": "2026-09-20"}
        )
    )
    assert listed["total"] == 1
    assert {item["value"] for item in listed["skills"]} >= {"general", "refund", "complaint"}

    await _ok(await client.delete(f"/api/v1/admin/org/shifts/{created['id']}"))
    empty = await _ok(await client.get("/api/v1/admin/org/shifts", params={"tenant": TENANT}))
    assert empty["total"] == 0


async def test_shift_validations(client: httpx.AsyncClient) -> None:
    """日期/时段/技能组/坐席存在性四类校验，全部中文可操作。"""
    await _seed_user("cs-valid")
    base = {"tenant": TENANT, "username": "cs-valid", "work_date": "2026-09-20"}

    bad_date = await client.post(
        "/api/v1/admin/org/shifts", json={**base, "work_date": "2026/09/20"}
    )
    assert bad_date.json()["code"] == 1001

    bad_time = await client.post(
        "/api/v1/admin/org/shifts",
        json={**base, "start_time": "18:00", "end_time": "09:00"},
    )
    assert bad_time.json()["code"] == 1001
    assert "晚于" in bad_time.json()["msg"]

    bad_skill = await client.post("/api/v1/admin/org/shifts", json={**base, "skill": "vip"})
    assert bad_skill.json()["code"] == 1001

    ghost = await client.post(
        "/api/v1/admin/org/shifts",
        json={**base, "username": "ghost"},
    )
    assert ghost.json()["code"] == 1004


async def test_performance_shape_and_privacy(client: httpx.AsyncClient) -> None:
    """绩效到人：无数据回空列表；响应自带隐私与分母口径说明。"""
    data = await _ok(await client.get("/api/v1/admin/org/performance", params={"tenant": TENANT}))
    assert data["items"] == []
    assert data["total"] == 0
    assert data["size"] == 20
    assert "不含买家标识" in data["privacy_note"]
    assert "接手过的会话数" in data["scope_note"]


async def test_freeze_self_and_last_admin_blocked(client: httpx.AsyncClient) -> None:
    """两条防锁死保护：不能冻结自己、不能冻结本租户唯一启用中的管理员。"""
    users = await _ok(await client.get("/api/v1/admin/users", params={"keyword": "admin"}))
    admin_row = users["items"][0]
    assert admin_row["status"] == "active"
    assert admin_row["status_label"] == "正常"

    self_resp = await client.post(
        f"/api/v1/admin/users/{admin_row['id']}/status", json={"frozen": True}
    )
    assert self_resp.json()["code"] == 1001
    assert "当前登录账号" in self_resp.json()["msg"]

    login_as(CurrentUser(username="ops-other", tenant=TENANT, roles=["admin"]))
    only_resp = await client.post(
        f"/api/v1/admin/users/{admin_row['id']}/status", json={"frozen": True}
    )
    assert only_resp.json()["code"] == 1001
    assert "唯一启用中的管理员" in only_resp.json()["msg"]


async def test_freeze_actually_blocks_login(client: httpx.AsyncClient) -> None:
    """冻结真的拒登（authenticate 抛中文 ValueError），解冻后恢复 —— 不是只改个字段好看。"""
    from app.services import auth_service

    user_id = await _seed_user("cs-freeze", roles="cs")
    frozen = await _ok(
        await client.post(f"/api/v1/admin/users/{user_id}/status", json={"frozen": True})
    )
    assert frozen["status_label"] == "已冻结"

    async for db in session_mod.get_db():
        with pytest.raises(ValueError, match="冻结"):
            await auth_service.authenticate(db, "cs-freeze", "pw-123456")
        break

    await _ok(await client.post(f"/api/v1/admin/users/{user_id}/status", json={"frozen": False}))
    async for db in session_mod.get_db():
        user = await auth_service.authenticate(db, "cs-freeze", "pw-123456")
        assert user.username == "cs-freeze"
        break

    listed = await _ok(
        await client.get("/api/v1/admin/users", params={"tenant": TENANT, "status": "frozen"})
    )
    assert listed["total"] == 0
