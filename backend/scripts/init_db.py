"""初始化库表与种子账号（手动兜底，对齐数据模型与存储设计.md §6）

用法（backend/ 目录下）：
    python scripts/init_db.py
账号取 Settings（SEED_TENANT / SEED_USERNAME / SEED_PASSWORD / SEED_ROLES，.env 可覆盖），
默认 demo-tenant / admin / admin123 / cs,kb。
注：后端启动时已幂等灌种子（SEED_ON_START），本脚本用于「不启动服务先建库」的场景。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db.seed import seed_on_startup
from app.db.session import init_models


async def _main() -> None:
    await init_models()
    created = await seed_on_startup()
    account = f"{settings.SEED_TENANT}/{settings.SEED_USERNAME}"
    print(f"seed user created: {account}" if created else f"seed user exists: {account}")


if __name__ == "__main__":
    asyncio.run(_main())
