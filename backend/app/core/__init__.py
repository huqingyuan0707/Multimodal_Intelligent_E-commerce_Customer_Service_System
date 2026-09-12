"""横切能力包（信封/错误码/鉴权/上下文/中间件，对齐 API 规范 §1-§3）

链路：middleware 打 trace → rbac 鉴权 → user_context 取人 → responses 信封返回。
"""

from __future__ import annotations
