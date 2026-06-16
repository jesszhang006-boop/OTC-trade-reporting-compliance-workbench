"""LEI 工具 wrapper。

稳定实现位于 src.engine；本文件只暴露 LEI 校验相关工具。
"""

from __future__ import annotations

from ..engine import lei_check_digits_valid, lei_to_number


__all__ = [
    "lei_check_digits_valid",
    "lei_to_number",
]
