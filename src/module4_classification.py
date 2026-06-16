"""事件合约分类分析模块 wrapper。

稳定实现位于 src.engine；本文件只暴露清晰的分类判断边界。
"""

from __future__ import annotations

from .engine import (
    EVENT_CONTRACT_UPI_SCHEMA,
    EVENT_ECONOMIC_FUNCTION_TESTS,
    cftc_event_contract_findings,
    classification_conclusion,
    event_contract_analysis,
    event_economic_function_test,
    event_source_facts,
    event_supervisory_flags,
    mas_event_contract_findings,
)


__all__ = [
    "EVENT_CONTRACT_UPI_SCHEMA",
    "EVENT_ECONOMIC_FUNCTION_TESTS",
    "cftc_event_contract_findings",
    "classification_conclusion",
    "event_contract_analysis",
    "event_economic_function_test",
    "event_source_facts",
    "event_supervisory_flags",
    "mas_event_contract_findings",
]
