"""ContextCompressionService — layered compression for Agent LLM context.

Implements the 4-stage compression pipeline:
  1. Tier assignment (head/mid/tail)
  2. Deduplication (>85% similarity → keep highest relevance)
  3. Structured extraction (OpenAPI, ERD, DAG, code)
  4. Token budget enforcement

Shared across all Agent instances via a class-level singleton.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(os.environ.get("AI_NATIVE_CONFIG_DIR", ".ai-native"))
_CONTENT_TYPE_HEAD = {"requirement_title", "acceptance_criteria", "rework_issues"}
_CONTENT_TYPE_MID = {"openapi", "erd", "dag", "code_diff", "test_report", "claude_md"}
_CONTENT_TYPE_TAIL = {"similar_requirements", "best_practices", "known_issues", "historical_reqs"}

# Default budget per state (used when .ai-native/context-budget.yaml is missing)
_DEFAULT_BUDGETS = {
    "analyzing": {"pct": 1.5, "max": 3000},
    "designing": {"pct": 3.0, "max": 6000},
    "reviewing": {"pct": 4.0, "max": 8000},
    "decomposing": {"pct": 3.0, "max": 6000},
    "developing": {"pct": 5.0, "max": 10000},
    "testing": {"pct": 3.0, "max": 6000},
    "reviewing_code": {"pct": 3.0, "max": 6000},
    "releasing": {"pct": 3.0, "max": 6000},
    "rework": {"pct": 6.0, "max": 12000},
}


def _load_budget_config() -> dict:
    path = _CONFIG_DIR / "context-budget.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _estimate_tokens(text: str) -> int:
    """Rough token estimation: 1 token ≈ 4 characters for CJK/mixed text."""
    return len(text) // 4


class ContextCompressionService:
    """Unified context compression for all Agents.

    Usage (from BaseAgentWorker):
        compressor = ContextCompressionService(config, llm_caller=self.call_llm)
        compressed_text = await compressor.prepare(context_package, budget, agent_id)
    """

    def __init__(self, config: dict | None = None, llm_caller=None):
        self.config = config or {}
        self.dedup_threshold = self.config.get("compression", {}).get("dedup_threshold", 0.85)
        self.llm_summarize_enabled = self.config.get("compression", {}).get("llm_summarize_enabled", False)
        self.structured_extract_enabled = self.config.get("compression", {}).get("structured_extract_enabled", True)
        self.llm_caller = llm_caller
        self._summary_cache: dict[str, tuple[str, float]] = {}  # key -> (text, mtime)

    def get_budget_for_state(self, state: str) -> int:
        budgets = self.config.get("budgets", _DEFAULT_BUDGETS)
        state_config = budgets.get(state, {"pct": 2.0, "max": 4000})
        window = self.config.get("model_window", 200000)
        pct_budget = int(window * state_config["pct"] / 100)
        return min(pct_budget, state_config["max"])

    async def prepare(self, context_package: dict, budget: int, agent_id: str) -> str:
        """Entry point: compress context_package into LLM-ready text within budget."""
        return await self.prepare_context(context_package, budget, agent_id)

    async def prepare_context(self, context_package: dict, budget: int, agent_id: str) -> str:
        """Compress structured context_package → LLM input text within token budget."""
        seq = _tier_context(context_package)
        seq = _deduplicate(seq, self.dedup_threshold)
        if self.structured_extract_enabled:
            seq = _structured_extract(seq)

        # Serialize: head → mid → tail, checking budget after each tier
        result_parts = []

        for item in seq:
            text = _serialize_item(item)
            if _estimate_tokens("".join(result_parts) + text) <= budget:
                result_parts.append(text)
            elif item.get("_tier") == "head":
                # Head items must always be included; if they don't fit, serialise compactly
                result_parts.append(_serialize_item(item, compact=True))
            # mid and tail items that don't fit are silently dropped

        if not result_parts:
            return json.dumps(context_package.get("requirement_context", {}), ensure_ascii=False)

        return "".join(result_parts)


# ── Tier assignment ─────────────────────────────────────────────────────

def _tier_context(context_package: dict) -> list[dict]:
    """Split context_package items into head/mid/tail tier items."""
    items = []
    req = context_package.get("requirement_context", {})
    artifacts = context_package.get("artifact_context", {})
    knowledge = context_package.get("knowledge_context", {})
    env = context_package.get("environment_context", {})
    rework = context_package.get("rework_context") or {}
    decisions = context_package.get("decisions_context") or {}

    # Head: must-have info
    items.append({"_tier": "head", "_type": "requirement_title",
                  "title": req.get("title", ""),
                  "description": req.get("description", "")[:300]})

    if req.get("acceptance_criteria"):
        items.append({"_tier": "head", "_type": "acceptance_criteria",
                      "criteria": req["acceptance_criteria"]})

    if rework and rework.get("issues"):
        items.append({"_tier": "head", "_type": "rework_issues",
                      "issues": rework["issues"]})

    # Mid: structured artifacts (compressed)
    for agent_id, artifact in artifacts.items():
        if isinstance(artifact, dict):
            for key in ("openapi", "erd", "dag", "test_report", "code_diff_summary"):
                if key in artifact:
                    items.append({"_tier": "mid", "_type": key,
                                  "_agent": agent_id, "content": artifact[key]})

    # Mid: environment info
    proj = env.get("project", {})
    if proj.get("claude_md_content"):
        items.append({"_tier": "mid", "_type": "claude_md",
                      "content": proj["claude_md_content"]})
    if proj.get("coding_conventions"):
        items.append({"_tier": "mid", "_type": "coding_conventions",
                      "content": proj["coding_conventions"]})

    # Mid: Gate decisions (for A9 developing state)
    resolved = decisions.get("resolved", {})
    if resolved:
        items.append({"_tier": "mid", "_type": "gate_decisions",
                      "resolved": resolved,
                      "source_gates": decisions.get("source_gates", []),
                      "approved_at": decisions.get("approved_at", "")})

    # Tail: knowledge base results (nice-to-have)
    for tier_key, tier_name in [("head", "head"), ("mid", "mid"), ("tail", "tail")]:
        for k_item in knowledge.get(tier_key, []):
            items.append({"_tier": "tail", "_type": "knowledge_" + tier_name,
                          "category": k_item.get("category", ""),
                          "content": k_item.get("content", ""),
                          "relevance": k_item.get("relevance", 0)})

    return items
    for tier_key, tier_name in [("head", "head"), ("mid", "mid"), ("tail", "tail")]:
        for k_item in knowledge.get(tier_key, []):
            items.append({"_tier": "tail", "_type": "knowledge_" + tier_name,
                          "category": k_item.get("category", ""),
                          "content": k_item.get("content", ""),
                          "relevance": k_item.get("relevance", 0)})

    return items


# ── Deduplication ───────────────────────────────────────────────────────

def _deduplicate(items: list[dict], threshold: float = 0.85) -> list[dict]:
    """Remove items with >threshold content overlap, keeping highest relevance."""
    seen = []
    result = []
    for item in items:
        content = str(item.get("content", ""))
        if not content:
            result.append(item)
            continue
        # Simple Jaccard-like dedup on character trigrams
        is_dup = False
        for prev in seen:
            prev_content = str(prev.get("content", ""))
            if prev_content and _content_similarity(content, prev_content) > threshold:
                # Keep the one with higher relevance
                if item.get("relevance", 0) > prev.get("relevance", 0):
                    seen.remove(prev)
                    result = [r for r in result if r is not prev]
                else:
                    is_dup = True
                    break
        if not is_dup:
            seen.append(item)
            result.append(item)
    return result


def _content_similarity(a: str, b: str) -> float:
    """Estimate text similarity via trigram overlap."""
    def trigrams(s):
        return set(s[i:i + 3] for i in range(len(s) - 2))
    ta = trigrams(a.lower())
    tb = trigrams(b.lower())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── Structured extraction ───────────────────────────────────────────────

def _structured_extract(items: list[dict]) -> list[dict]:
    """Compress mid-tier items via structured extraction."""
    result = []
    for item in items:
        if item.get("_tier") != "mid":
            result.append(item)
            continue
        content_type = item.get("_type", "")
        content = item.get("content", {})

        if content_type == "openapi" and isinstance(content, dict):
            paths = (content.get("paths", {}) or content.get("endpoints", []))
            if isinstance(paths, dict):
                endpoints = []
                for path, methods in list(paths.items())[:10]:
                    for method, details in (methods or {}).items():
                        if isinstance(details, dict):
                            endpoints.append({
                                "method": method.upper(),
                                "path": path,
                                "summary": details.get("summary", ""),
                                "parameters": [p.get("name") for p in details.get("parameters", [])[:5]],
                                "responses": list(details.get("responses", {}).keys())[:3],
                            })
                item["summary"] = endpoints
            elif isinstance(paths, list):
                item["summary"] = []
                for e in paths[:10]:
                    if isinstance(e, dict):
                        item["summary"].append({
                            "path": e.get("path", ""),
                            "method": e.get("method", ""),
                        })
                    elif isinstance(e, str):
                        item["summary"].append({"path": e, "method": "?"})
            item.pop("content", None)

        elif content_type == "erd" and isinstance(content, dict):
            tables = content.get("tables", content.get("entities", []))
            if isinstance(tables, list):
                item["summary"] = []
                for t in tables[:10]:
                    if isinstance(t, dict):
                        cols = t.get("columns", [])
                        item["summary"].append({
                            "name": t.get("name", ""),
                            "columns": [c.get("name", c) if isinstance(c, dict) else str(c) for c in cols[:8]],
                        })
                    elif isinstance(t, str):
                        item["summary"].append({"name": t, "columns": []})
            relationships = content.get("relationships", [])
            if relationships:
                item["fk_summary"] = [
                    {"from": r.get("from", ""), "to": r.get("to", ""),
                     "type": r.get("type", "")}
                    for r in relationships[:20]
                ]
            item.pop("content", None)

        elif content_type == "dag" and isinstance(content, dict):
            item["summary"] = {
                "nodes": [
                    {"id": n.get("id", ""), "title": n.get("title", ""),
                     "edges_out": len(n.get("edges", n.get("dependencies", [])))}
                    for n in content.get("nodes", [])[:20]
                ],
                "edges": [
                    {"from": e.get("from", ""), "to": e.get("to", "")}
                    for e in content.get("edges", [])[:30]
                ],
            }
            item.pop("content", None)

        elif content_type == "code_diff_summary" and isinstance(content, dict):
            files = content.get("files", content.get("changes", []))
            item["summary"] = [
                {"file": f.get("file", f.get("path", "")),
                 "additions": f.get("additions", "+"), "deletions": f.get("deletions", "-")}
                for f in (files if isinstance(files, list) else [])[:15]
            ]
            item.pop("content", None)

        elif content_type == "test_report" and isinstance(content, dict):
            item["summary"] = {
                "passed": content.get("passed", content.get("pass_count", "?")),
                "failed": content.get("failed", content.get("fail_count", "?")),
                "total": content.get("total", "?"),
                "failures": [
                    f.get("name", f.get("test", ""))[:100]
                    for f in content.get("failures", [])[:10]
                ],
            }
            item.pop("content", None)

        else:
            result.append(item)
            continue

        result.append(item)
    return result


# ── Serialization ───────────────────────────────────────────────────────

def _serialize_item(item: dict, compact: bool = False) -> str:
    """Serialize a context item into a text line/block for LLM consumption."""
    tier = item.get("_tier", "mid")
    ctype = item.get("_type", "")
    label = f"[{tier}:{ctype}]"

    if "summary" in item:
        summary = item["summary"]
        if isinstance(summary, list) and len(summary) > 0:
            lines = [f"\n{label}"]
            for s in summary:
                if isinstance(s, dict):
                    lines.append("  - " + json.dumps(s, ensure_ascii=False))
                else:
                    lines.append("  - " + str(s)[:200])
            return "\n".join(lines[:30]) + "\n"
        elif isinstance(summary, dict):
            return f"\n{label} {json.dumps(summary, ensure_ascii=False)}\n"

    content = item.get("content", "")
    if isinstance(content, str) and content:
        if compact:
            return f"\n{label} {content[:200]}\n"
        return f"\n{label} {content[:800]}\n"

    # Fallback: serialize primitive values
    if "title" in item:
        return f"\n{label} {item['title']}: {item.get('description', '')[:200]}\n"
    if "criteria" in item:
        return f"\n{label} " + "; ".join(str(c) for c in item["criteria"][:5]) + "\n"
    if "issues" in item:
        return f"\n{label} " + "; ".join(
            i.get("description", str(i))[:100] for i in item["issues"][:5]
        ) + "\n"
    if "resolved" in item:
        decisions_str = ", ".join(
            f"{k}={v}" for k, v in item["resolved"].items()
        )
        return f"\n{label} {decisions_str}\n"

    return ""
