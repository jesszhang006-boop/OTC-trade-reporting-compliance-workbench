"""报告与输出模块 wrapper。

稳定实现位于 src.engine；本文件只暴露清晰的输出边界。
"""

from __future__ import annotations

from .engine import (
    summarize,
    write_dashboard,
    write_findings_csv,
    write_json,
    write_outputs,
)


__all__ = [
    "summarize",
    "write_dashboard",
    "write_findings_csv",
    "write_json",
    "write_outputs",
]
