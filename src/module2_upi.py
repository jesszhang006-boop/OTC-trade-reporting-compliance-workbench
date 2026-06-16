"""UPI 与 codeset 校验模块 wrapper。

稳定实现位于 src.engine；本文件只暴露清晰的产品识别边界。
"""

from __future__ import annotations

from .engine import (
    codeset_findings,
    load_codeset,
    load_codesets,
    lookup_upi,
    map_product,
    product_template_path,
    upi_findings,
    validate_currency,
    validate_reference_rate,
)


__all__ = [
    "codeset_findings",
    "load_codeset",
    "load_codesets",
    "lookup_upi",
    "map_product",
    "product_template_path",
    "upi_findings",
    "validate_currency",
    "validate_reference_rate",
]
