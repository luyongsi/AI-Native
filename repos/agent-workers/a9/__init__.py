"""
A9 Dual-Brain Module

Exports:
- CoderModule: Code generation brain
- AuditorModule: Code review brain
- A9DevAgent: Main orchestrator
- A9Metrics: Observability
- StaticAnalyzer: Static analysis utilities
"""

from a9.coder import CoderModule
from a9.auditor import AuditorModule
from a9.a9_dev_agent import A9DevAgent
from a9.metrics import A9Metrics, A9MetricsCollector
from a9.static_analyzer import StaticAnalyzer

__all__ = [
    "CoderModule",
    "AuditorModule",
    "A9DevAgent",
    "A9Metrics",
    "A9MetricsCollector",
    "StaticAnalyzer",
]
