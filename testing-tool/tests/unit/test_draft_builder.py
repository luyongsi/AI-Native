"""
DraftBuilder streaming parser tests — T-PR-001 through T-PR-007.

Tests JSON completeness detection, chunk accumulation, escape handling,
multiple JSON objects, garbage prefix handling, and array-wrapper rejection.

Run with:
  pytest repos/agent-workers/tests/test_draft_builder.py -v
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


# ══════════════════════════════════════════════════════════════════════════
# Helper: reach into DraftBuilder._try_parse_json
# ══════════════════════════════════════════════════════════════════════════

def _parse(buffer: str) -> tuple[dict | None, int]:
    from a1.analyzer.draft_builder import DraftBuilder
    return DraftBuilder._try_parse_json(buffer)


# ══════════════════════════════════════════════════════════════════════════
# T-PR-001: Complete JSON → parsed in one shot
# ══════════════════════════════════════════════════════════════════════════

def test_pr_001_complete_json_parsed():
    buffer = (
        '{"title":"测试","description":"这是测试","domain":"general",'
        '"entities":[],"use_cases":[],"acceptance_criteria":[],'
        '"constraints":[],"risks":[],"estimated_cost":null}'
    )
    result, consumed = _parse(buffer)

    assert result is not None
    assert result["title"] == "测试"
    assert result["domain"] == "general"
    assert consumed == len(buffer)


# ══════════════════════════════════════════════════════════════════════════
# T-PR-002: Incomplete JSON → wait for more chunks
# ══════════════════════════════════════════════════════════════════════════

def test_pr_002_incomplete_json_wait():
    buffer = '{"title":"测试","description":"这是测试","entities":['
    result, consumed = _parse(buffer)

    assert result is None
    assert consumed == 0


# ══════════════════════════════════════════════════════════════════════════
# T-PR-003: Two consecutive JSON → only first is consumed
# ══════════════════════════════════════════════════════════════════════════

def test_pr_003_two_consecutive_json():
    v1 = '{"title":"v1","domain":"general"}'
    v2 = '{"title":"v2","domain":"auth"}'
    buffer = v1 + "   " + v2

    # First parse
    result1, consumed1 = _parse(buffer)
    assert result1 is not None
    assert result1["title"] == "v1"

    # Second parse on remainder
    remaining = buffer[consumed1:]
    result2, consumed2 = _parse(remaining)
    assert result2 is not None
    assert result2["title"] == "v2"


# ══════════════════════════════════════════════════════════════════════════
# T-PR-004: Garbage characters before JSON → skipped
# ══════════════════════════════════════════════════════════════════════════

def test_pr_004_garbage_before_json():
    buffer = '这是一些解释文本\n{"title":"正式草案","domain":"general"}'
    result, consumed = _parse(buffer)

    assert result is not None
    assert result["title"] == "正式草案"
    # consumed should include the garbage prefix
    assert consumed == len(buffer)


# ══════════════════════════════════════════════════════════════════════════
# T-PR-005: Non-dict JSON → rejected (array wrapper detection)
# ══════════════════════════════════════════════════════════════════════════

def test_pr_005_array_wrapper_rejected():
    buffer = '[{"title":"array","domain":"general"}]'
    result, consumed = _parse(buffer)

    # Should reject because '[' precedes the first '{' in the prefix
    assert result is None
    assert consumed == 0


# ══════════════════════════════════════════════════════════════════════════
# T-PR-006: Streaming chunk accumulation → multiple yields
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pr_006_streaming_chunks_multiple_yields():
    """Simulate 3 chunks arriving, verify 2 yields (v1 at chunk3, v2 at chunk4)."""
    from a1.analyzer.draft_builder import DraftBuilder

    builder = DraftBuilder()
    builder.api_key = ""  # prevent actual LLM calls

    # Override _stream_llm to emit our test chunks
    test_chunks = [
        '{"title":"用户管理","domain":"',
        'user_management"}',
        '{"title":"用户管理 v2","domain":"user_management","description":"改进版"}',
    ]

    async def _mock_stream(*args, **kwargs):
        for c in test_chunks:
            yield c

    builder._stream_llm = _mock_stream

    ctx = {
        "history": [],
        "current_draft": None,
        "knowledge": {},
        "cycle": 0,
        "user_message": "做一个用户管理系统",
    }

    results = []
    async for draft in builder.stream_analyze("做一个用户管理系统", ctx):
        results.append(draft)

    assert len(results) >= 2, f"Expected >=2 yields, got {len(results)}: {results}"
    # First yield should have the initial version
    assert results[0].get("title") == "用户管理"
    # Last yield should be the v2 version
    assert results[-1].get("title") == "用户管理 v2"


# ══════════════════════════════════════════════════════════════════════════
# T-PR-007: Escaped quotes inside JSON string → correct closure detection
# ══════════════════════════════════════════════════════════════════════════

def test_pr_007_escaped_quotes():
    buffer = '{"title":"他说\\"你好\\"","domain":"general"}'
    result, consumed = _parse(buffer)

    assert result is not None
    assert result["title"] == '他说"你好"'
    assert consumed == len(buffer)


def test_pr_007b_escaped_quotes_mixed():
    """Additional: non-escaped quote mix within a value."""
    buffer = '{"title":"test","description":"a\\"b\\"c","domain":"x"}'
    result, consumed = _parse(buffer)

    assert result is not None
    assert result["description"] == 'a"b"c'
