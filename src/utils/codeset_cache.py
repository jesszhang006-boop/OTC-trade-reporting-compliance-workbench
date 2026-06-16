"""Codeset 缓存 wrapper。

稳定实现位于 src.engine；本文件只暴露 codeset 加载工具。
"""

from __future__ import annotations

from ..engine import load_codeset, load_codesets


__all__ = [
    "load_codeset",
    "load_codesets",
]
