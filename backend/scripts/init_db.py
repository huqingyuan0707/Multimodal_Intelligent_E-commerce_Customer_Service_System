"""初始化库表与种子用户（开发联调用，对齐数据模型 §6）

用法（backend/ 目录下）：
    python scripts/init_db.py
默认种子：租户 demo-tenant / 用户 demo / 密码取环境变量 SEED_PASSWORD（缺省 demo1234）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import get_engine, init_models  # noqa: E402


async def _main() -> None:
    await init_models()
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    password = os.getenv("SEED_PASSWORD", "demo1234")
    async with factory() as db:
        exists = (
            await db.execute(
                select(User).where(User.tenant == "demo-tenant", User.username == "demo")
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                User(
                    tenant="demo-tenant",
                    username="demo",
                    pwd_hash=hash_password(password),
                    roles="cs,kb",
                )
            )
            await db.commit()
            print("seed user created: demo-tenant/demo")
        else:
            print("seed user exists: demo-tenant/demo")


if __name__ == "__main__":
    asyncio.run(_main())
