"""PII 口径唯一出处（手机/身份证/邮箱正则，对齐数据模型 §2 留痕节）

链路：context_service.sanitize_text（历史进 LLM 清洗）+ memory_service（PII 永不进记忆守门）
      共用同一组正则，禁止各处自写一份。
"""

from __future__ import annotations

import re

MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
IDCARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def contains_pii(text: str) -> bool:
    """是否含 PII（手机/身份证/邮箱任一命中即 True，空串 False）。"""
    if not text:
        return False
    return bool(MOBILE.search(text) or IDCARD.search(text) or EMAIL.search(text))
