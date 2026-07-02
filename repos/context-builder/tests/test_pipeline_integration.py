"""Integration tests for the Context Builder pipeline."""

import pytest
from unittest.mock import Mock, patch, PropertyMock

from context_item import ContextItem, SelectResult
from embedder import Embedder, get_embedder
from pipeline import ContextBuilder
from selector import ContextSelector


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_item(content: str, relevance: float, tokens: int,
               item_type: str = "code", file: str = "test.py") -> ContextItem:
    """Factory for a ContextItem with sensible defaults."""
    return ContextItem(
        type=item_type,
        content=content,
        relevance=relevance,
        position="mid",
        tokens=tokens,
        file=file,
        compressed=False,
    )


def _select_result(*items: ContextItem, discarded: int = 0) -> SelectResult:
    """Build a SelectResult from items."""
    tokens_used = sum(it.tokens for it in items)
    return SelectResult(items=list(items), tokens_used=tokens_used, discarded=discarded)


def _assert_has_stage(events: list, stage: str) -> dict:
    """Return the first event dict matching *stage*, or fail."""
    for ev in events:
        if ev.get("stage") == stage:
            return ev
    pytest.fail(f"Expected pipeline event for stage '{stage}' not found in {events}")


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """Full pipeline integration tests covering healthy, degraded, and failure paths."""

    # ---- Test 1: full pipeline healthy -----------------------------------

    def test_full_pipeline_healthy(self):
        """Build context with default hash embedder — every stage should run."""
        items = [
            _make_item("def foo():\n    pass\n", relevance=0.9, tokens=200),
            _make_item("class Bar:\n    pass\n", relevance=0.7, tokens=300),
            _make_item("# TODO refactor", relevance=0.5, tokens=100),
            _make_item("old log line", relevance=0.3, tokens=50, item_type="log"),
            _make_item("archive entry", relevance=0.1, tokens=80, item_type="doc"),
        ]

        # Mock the selector so we don't need a real DB
        selector = Mock(spec=ContextSelector)
        selector.select.return_value = _select_result(*items)

        builder = ContextBuilder(selector=selector)
        result = builder.build_context(
            target_agent="A9",
            req_id="req-001",
            task_id="task-001",
            max_tokens=8000,
        )

        # All stages should have run
        events = result["pipeline_events"]
        _assert_has_stage(events, "select")
        _assert_has_stage(events, "order")
        _assert_has_stage(events, "compress")
        _assert_has_stage(events, "isolate")

        # Structural fields should be present
        assert "head" in result
        assert "mid" in result
        assert "tail" in result
        assert "discarded" in result

        # Meta should report healthy embedding
        assert result["meta"]["embedding_status"] == "healthy"
        assert result["meta"]["pipeline_version"] == "1.0"

        # At least some items should be non-discarded (budget is large)
        non_discarded = sum(
            len(result[k]) for k in ("head", "mid", "tail")
        )
        assert non_discarded > 0, "Expected at least one active item"

    # ---- Test 2: degraded embedding -------------------------------------

    def test_pipeline_degraded_embedding(self):
        """Monkey-patch remote_healthy to False — meta should report degraded."""
        items = [
            _make_item("useful snippet", relevance=0.9, tokens=200),
        ]
        selector = Mock(spec=ContextSelector)
        selector.select.return_value = _select_result(*items)
        embedder = Embedder()

        builder = ContextBuilder(selector=selector, embedder=embedder)

        # Force the embedder to report unhealthy
        with patch.object(Embedder, "remote_healthy", new_callable=PropertyMock) as mock_rh:
            mock_rh.return_value = False
            result = builder.build_context(
                target_agent="A9",
                max_tokens=8000,
            )

        assert result["meta"]["embedding_status"] == "degraded"
        # Pipeline must still complete
        assert len(result["pipeline_events"]) >= 4
        assert len(result["head"] + result["mid"] + result["tail"]) > 0

    # ---- Test 3: select failure returns empty ----------------------------

    def test_select_failure_returns_empty(self):
        """If selector.select() raises, pipeline returns empty items with error event."""
        selector = Mock(spec=ContextSelector)
        selector.select.side_effect = RuntimeError("DB connection lost")

        builder = ContextBuilder(selector=selector)
        result = builder.build_context(target_agent="A9", max_tokens=4000)

        # Verify empty result
        assert result["items"] == [] if "items" in result else (
            result["head"] == [] and result["mid"] == [] and result["tail"] == []
        )
        assert result["tokens_used"] == 0

        # Verify error event
        select_ev = _assert_has_stage(result["pipeline_events"], "select")
        assert "error" in select_ev
        assert "DB connection lost" in select_ev["error"]

    # ---- Test 4: high fill rate triggers force_compact ------------------

    def test_high_fill_rate_triggers_force_compact(self):
        """Items exceeding critical threshold (0.75) should trigger force_compact."""
        # Build items whose tokens collectively exceed critical_threshold * max_tokens
        max_tokens = 1000
        items = [
            _make_item("big chunk A", relevance=0.9, tokens=400),
            _make_item("big chunk B", relevance=0.8, tokens=400),
            _make_item("big chunk C", relevance=0.7, tokens=400),
        ]
        # tokens_used = 1200, max_tokens=1000 -> fill_rate = 1.2 > 0.75

        selector = Mock(spec=ContextSelector)
        selector.select.return_value = _select_result(*items)

        builder = ContextBuilder(selector=selector)
        result = builder.build_context(
            target_agent="A9",
            max_tokens=max_tokens,
        )

        # Check isolate stage event
        isolate_ev = _assert_has_stage(result["pipeline_events"], "isolate")
        assert isolate_ev.get("action") == "force_compact", (
            f"Expected force_compact, got {isolate_ev.get('action')}"
        )
        assert isolate_ev["fill_rate"] > builder.isolator.critical_threshold
