"""
a12/__init__.py — A12 Code Review Agent Sub-modules

Exports: CrossModuleAnalyzer, AutoFixPatcher, ReviewReportGenerator
"""

from __future__ import annotations

from .cross_module_analyzer import CrossModuleAnalyzer
from .auto_fix_patcher import AutoFixPatcher
from .review_report import ReviewReportGenerator

__all__ = [
    "CrossModuleAnalyzer",
    "AutoFixPatcher",
    "ReviewReportGenerator",
]
