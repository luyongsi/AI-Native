"""
Pytest configuration for testing-tool tests.

Adds repos/agent-workers to sys.path so tests can import modules like:
    from a1.agent import A1Agent
    from a1.analyzer.draft_builder import DraftBuilder
"""
import sys
from pathlib import Path

AGENT_WORKERS_ROOT = Path(__file__).resolve().parents[2] / "repos" / "agent-workers"

if AGENT_WORKERS_ROOT.exists():
    sys.path.insert(0, str(AGENT_WORKERS_ROOT))
