"""共享模型类型别名。

稳定实现位于 src.engine；本文件提供轻量 typing 名称，保持模块边界清晰。
"""

from __future__ import annotations

from typing import Any, TypeAlias

from .engine import CONVENTIONAL_ASSET_CLASSES, EVENT_ASSET_CLASS


Trade: TypeAlias = dict[str, Any]
Finding: TypeAlias = dict[str, str]
ParseResult: TypeAlias = dict[str, Any]
UPIResult: TypeAlias = dict[str, Any]
AnalyzedTrade: TypeAlias = dict[str, Any]
ComplianceResults: TypeAlias = dict[str, Any]


__all__ = [
    "AnalyzedTrade",
    "ComplianceResults",
    "CONVENTIONAL_ASSET_CLASSES",
    "EVENT_ASSET_CLASS",
    "Finding",
    "ParseResult",
    "Trade",
    "UPIResult",
]
