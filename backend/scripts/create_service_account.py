"""外部 Agent 服务账号创建/口令轮换（对齐联动方案 §7.3，不经过 SEED_* 演示通道）

用法（backend/ 目录下，口令只走环境变量或交互输入，禁止写进命令行）：
    $env:SERVICE_ACCOUNT_PASSWORD='强口令（至少 8 位，勿用演示默认口令）'
    python scripts/create_service_account.py --tenant demo-tenant
    python scripts/create_service_account.py --tenant demo-tenant --reset   # 存量改密/补角色

建号后还需在 .env 里把账号写进 OFFICE_AGENT_SERVICE_ACCOUNTS（默认空 = 不采纳
X-On-Behalf-Of），否则对端透传的真实发起人会被忽略并告警。
角色默认取 Settings.OFFICE_AGENT_SERVICE_ROLES（读工具 Scope + agent:gateway 入口令牌），
缺任一 Scope 会让对端工具调用被 4006 硬拦。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db.session import get_engine, init_models
from app.services.admin_bootstrap import ensure_admin

DEFAULT_USERNAME = "svc-office-agent"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="创建外部 Agent 服务账号（幂等，口令走环境变量或交互输入）"
    )
    parser.add_argument("--tenant", required=True, help="租户编码（与 users.tenant 同源）")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help=f"用户名（默认 {DEFAULT_USERNAME}）")
    parser.add_argument(
        "--roles", default=settings.OFFICE_AGENT_SERVICE_ROLES, help="逗号分隔角色"
    )
    parser.add_argument("--reset", action="store_true", help="已存在时重设密码并补齐角色")
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    password = os.getenv("SERVICE_ACCOUNT_PASSWORD") or getpass.getpass("服务账号口令（输入不回显）：")
    if not password:
        print("FAIL: 未提供口令（SERVICE_ACCOUNT_PASSWORD 为空且交互输入为空）")
        return 1
    await init_models()
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        try:
            result = await ensure_admin(
                db,
                tenant=args.tenant,
                username=args.username,
                password=password,
                roles=args.roles,
                reset=args.reset,
            )
        except Exception as exc:
            print(f"FAIL: {exc}")
            return 1
    hint = {
        "created": "已创建",
        "exists": "已存在（未改动，加 --reset 可改密并补角色）",
        "reset": "已重设密码",
    }
    print(f"OK: 服务账号 {args.tenant}/{args.username}{hint[result]}")
    if args.username not in settings.OFFICE_AGENT_SERVICE_ACCOUNTS:
        print(
            f"提醒: 请在 .env 设置 OFFICE_AGENT_SERVICE_ACCOUNTS=['{args.username}']，"
            "否则对端 X-On-Behalf-Of 会被忽略并告警"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))