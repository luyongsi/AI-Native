"""
a12/__init__.py — A12 Code Review Agent Sub-modules

Exports: CrossModuleAnalyzer, AutoFixPatcher, ReviewReportGenerator,
         SecurityScanner, CWEMapper
"""

from __future__ import annotations

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == "CrossModuleAnalyzer":
        from .cross_module_analyzer import CrossModuleAnalyzer
        return CrossModuleAnalyzer
    elif name == "AutoFixPatcher":
        from .auto_fix_patcher import AutoFixPatcher
        return AutoFixPatcher
    elif name == "ReviewReportGenerator":
        from .review_report import ReviewReportGenerator
        return ReviewReportGenerator
    elif name == "SecurityScanner":
        from .security_scanner import SecurityScanner
        return SecurityScanner
    elif name == "CWEMapper":
        from .cwe_mapper import CWEMapper
        return CWEMapper
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CrossModuleAnalyzer",
    "AutoFixPatcher",
    "ReviewReportGenerator",
    "SecurityScanner",
    "CWEMapper",
]


