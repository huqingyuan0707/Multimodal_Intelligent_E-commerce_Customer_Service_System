"""错误码分段（新增必须落号段，对齐 API 规范 §2）

链路：services 抛码 → endpoints fail() → 前端按码分支（含 1002 走 handle401）。
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """1xxx 通用 / 2xxx 对话 / 3xxx 业务 / 4xxx 任务 / 5xxx 系统。"""

    OK = 0
    PARAM_INVALID = 1001
    UNAUTHORIZED = 1002
    FORBIDDEN = 1003
    NOT_FOUND = 1004
    QUOTA_EXCEEDED = 1005
    RATE_LIMITED = 1006
    LLM_FAILED = 2000
    NO_EVIDENCE = 2001
    CONVERSATION_LIMITED = 2002
    UNSAFE_CONTENT = 2003
    IMAGE_TOO_LARGE = 2004
    ORDER_NOT_FOUND = 3001
    ORDER_NOT_OWNED = 3002
    REFUND_NEED_APPROVAL = 3003
    STOCK_SHORTAGE = 3004
    ORDER_STATE_ILLEGAL = 3005
    COUPON_EXHAUSTED = 3006
    RISK_BLOCKED = 3007
    TASK_NOT_FOUND = 4001
    TASK_TIMEOUT = 4002
    APPROVAL_REQUIRED = 4003
    APPROVAL_DENIED = 4004
    INTERNAL = 5000
    UPSTREAM_FAILED = 5001
    MODEL_UNAVAILABLE = 5002


class BusinessError(Exception):
    """业务失败（带号段码 + 中文可操作提示）。

    链路：services 抛 BusinessError → main.py 异常处理器统一转 fail() 信封。
    这样端点只负责解析入参与调服务，业务分支判断全部留在服务层（分层红线）。
    """

    def __init__(self, code: ErrorCode, msg: str, http_status: int = 400) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.http_status = http_status
