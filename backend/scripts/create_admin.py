"""生产首个管理员创建/口令轮换（对齐数据模型与存储设计.md §6，不经过 SEED_* 演示通道）

用法（backend/ 目录下，口令只能走环境变量或交互输入，禁止写进命令行）：
    $env:ADMIN_PASSWORD='强口令（至少 8 位，勿用演示默认口令）'
    python scripts/create_admin.py --tenant acme --username ops --roles admin
    python scripts/create_admin.py --tenant acme --username ops --reset  # 存量改密/补角色
生产前置：ENV=prod 且 SEED_ON_START/B2B_SEED_DEMO/KB_SEED_DEMO 全关（否则启动即报错）。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import get_engine, init_models
from app.services.admin_bootstrap import ensure_admin


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="创建生产首个管理员（幂等，口令走环境变量或交互输入）"
    )
    parser.add_argument("--tenant", required=True, help="租户编码（与 users.tenant 同源）")
    parser.add_argument("--username", required=True, help="用户名")
    parser.add_argument("--roles", default="admin", help="逗号分隔角色（默认 admin）")
    parser.add_argument("--reset", action="store_true", help="已存在时重设密码并补齐角色")
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("管理员口令（输入不回显）：")
    if not password:
        print("FAIL: 未提供口令（ADMIN_PASSWORD 为空且交互输入为空）")
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
        "exists": "已存在（未改动，加 --reset 可改密）",
        "reset": "已重设密码",
    }
    print(f"OK: 管理员 {args.tenant}/{args.username}{hint[result]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
