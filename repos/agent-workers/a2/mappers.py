"""
mappers.py — Data format mapping layer for A2 Knowledge Analyst.

Bridges the gap between existing sub-module outputs (feasibility.py,
conflict_detector.py) and the data dictionary schema (section 5.2-5.5).

All mapping functions are async — the caller (A2KnowledgeAnalyst) is
responsible for the async orchestration and providing assessor/detector
instances.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Feasibility mapping ───────────────────────────────────────────────────


async def build_feasibility_assessment(
    draft: dict,
    domain_risks: list[dict],
    assessor=None,  # FeasibilityAssessor instance
    call_llm=None,  # async callable for LLM
) -> dict:
    """Map 1D feasibility output → 2D data-dictionary §5.2 structure.

    technical feasibility: from FeasibilityAssessor.assess()
    business feasibility: from domain_risks + LLM (heuristic fallback)

    Returns:
        {technical: {feasible, assessment, concerns},
         business:  {feasible, assessment, concerns},
         risk_level: "low"|"medium"|"high",
         risk_rationale: str}
    """
    # ── technical feasibility ──
    raw = {"feasible": True, "risk_level": "low", "concerns": [], "confidence": 0.85}
    if assessor is not None:
        try:
            raw = await assessor.assess(draft)
        except Exception as e:
            logger.warning("FeasibilityAssessor failed: %s — using defaults", e)

    technical = {
        "feasible": raw.get("feasible", True),
        "assessment": (
            "; ".join(raw["concerns"])
            if raw.get("concerns")
            else "技术栈支持，无明显技术阻碍"
        ),
        "concerns": raw.get("concerns", []),
    }

    # ── business feasibility ──
    business = await _assess_business_feasibility(draft, domain_risks, call_llm)

    # ── risk rationale ──
    risk_rationale = _build_risk_rationale(raw, domain_risks)

    return {
        "technical": technical,
        "business": business,
        "risk_level": raw.get("risk_level", technical.get("risk_level", "low")),
        "risk_rationale": risk_rationale,
    }


async def _assess_business_feasibility(
    draft: dict,
    domain_risks: list[dict],
    call_llm=None,
) -> dict:
    """Assess business feasibility with LLM, falling back to heuristic."""
    title = draft.get("title", "")
    domain = draft.get("domain", "general")

    risk_text = "\n".join(
        f"- {r.get('risk_name', r.get('risk', ''))}: {r.get('description', '')}"
        for r in (domain_risks or [])[:5]
    ) or "无已知领域风险"

    prompt = (
        f"需求: {title}\n领域: {domain}\n已知风险:\n{risk_text}\n"
        "判断此需求在当前业务方向上是否可行。返回 JSON: "
        '{"feasible": bool, "assessment": "简要评估", "concerns": ["顾虑1"]}'
    )

    if call_llm is not None:
        try:
            llm_result = await call_llm(
                [{"role": "user", "content": prompt}],
                task_type="knowledge_analysis",
                req_id="",
                temperature=0.3,
                max_tokens=500,
            )
            if llm_result:
                data = json.loads(_extract_json_block(llm_result))
                return {
                    "feasible": data.get("feasible", True),
                    "assessment": data.get("assessment", "LLM 评估完成"),
                    "concerns": data.get("concerns", []),
                }
        except Exception as e:
            logger.warning("Business feasibility LLM failed: %s", e)

    # heuristic fallback
    return {
        "feasible": True,
        "assessment": "业务可行性评估通过（启发式）",
        "concerns": (
            ["LLM 不可用，未进行深度业务分析"] if not domain_risks else []
        ),
    }


def _build_risk_rationale(raw_feasibility: dict, domain_risks: list[dict]) -> str:
    """Combine technical concerns with domain risk descriptions."""
    parts = []
    concerns = raw_feasibility.get("concerns", [])
    if concerns:
        parts.append("技术风险: " + "; ".join(concerns))
    domain_descs = [
        r.get("description", r.get("risk_name", r.get("risk", "")))
        for r in (domain_risks or [])[:3]
    ]
    if domain_descs:
        parts.append("领域风险: " + "; ".join(domain_descs))
    return "\n".join(parts) if parts else "无明显风险"


# ── Conflict mapping ──────────────────────────────────────────────────────


async def build_conflicts(
    draft: dict,
    similar_reqs: list[dict],
    detector=None,  # ConflictDetector instance
) -> list[dict]:
    """Detect conflicts and map output → data-dictionary §5.5 format.

    Extracts existing specs from similar_reqs metadata, adapts entity
    formats, calls ConflictDetector.detect(), and remaps fields.

    Returns:
        [{id, related_system, type, description, severity}]
    """
    # extract existing specs with entities from similar requirements
    existing_specs = []
    for r in (similar_reqs or [])[:5]:
        meta = r.get("metadata", {})
        if meta.get("entities"):
            existing_specs.append({
                "id": r.get("content_id", ""),
                "entities": meta["entities"],
            })

    if not existing_specs:
        logger.debug("No existing specs with entities for conflict detection")
        return []

    # adapt formats (attributes[] → fields[])
    adapted_draft = _adapt_draft_for_detector(draft)
    adapted_specs = [_adapt_spec_for_detector(s) for s in existing_specs]

    if detector is None:
        return []

    try:
        raw = await detector.detect(adapted_draft, adapted_specs)
    except Exception as e:
        logger.warning("ConflictDetector failed: %s", e)
        return []

    # map output → data dictionary §5.5
    conflicts = []
    for i, c in enumerate(raw.get("conflicts", [])):
        ent = c.get("entity", "")
        field = c.get("field", "")
        attr = c.get("attribute", "")
        conflicts.append({
            "id": f"conflict_{i + 1}",
            "related_system": ent,
            "type": _map_conflict_type(attr),
            "description": (
                f"'{ent}'的'{field}'字段的'{attr}'属性："
                f"现有值'{c.get('existing_value', '')}' vs 新值'{c.get('new_value', '')}'"
            ),
            "severity": c.get("severity", "low"),
        })

    return conflicts


def _adapt_draft_for_detector(draft: dict) -> dict:
    """Convert data-dict entities [{name, attributes: [string]}] →
       detector format [{name, fields: [{name, type, required}]}]."""
    entities = draft.get("entities", [])
    adapted = []
    for ent in entities:
        attrs = ent.get("attributes", [])
        fields = [
            {"name": a, "type": "unknown", "required": False}
            for a in attrs
        ]
        adapted.append({
            "name": ent.get("name", ""),
            "fields": fields,
        })
    return {"entities": adapted}


def _adapt_spec_for_detector(spec: dict) -> dict:
    """Same adaptation for an existing spec's entities."""
    entities = spec.get("entities", [])
    adapted = []
    for ent in entities:
        # already in fields format?
        if ent.get("fields"):
            adapted.append(ent)
            continue
        attrs = ent.get("attributes", [])
        fields = [
            {"name": a, "type": "unknown", "required": False}
            for a in attrs
        ]
        adapted.append({
            "name": ent.get("name", ""),
            "fields": fields,
        })
    return {"id": spec.get("id", ""), "entities": adapted}


def _map_conflict_type(attribute: str) -> str:
    """Map attribute name → data-dictionary §5.5 conflict type."""
    if attribute in ("type", "format", "precision", "scale"):
        return "data_model"
    if attribute == "enum_values":
        return "business_flow"
    if attribute == "service_boundary":
        return "service_boundary"
    return "field_naming"


# ── Confirmation checklist ────────────────────────────────────────────────


_CHECKLIST_TEMPLATES = [
    {
        "id": "check_01",
        "category": "requirement_clarity",
        "item": "需求边界是否清晰？有无遗漏的上下游依赖？",
        "priority": "high",
    },
    {
        "id": "check_02",
        "category": "technical_risk",
        "item": "技术方案是否考虑了已知风险点？能否在现有架构上实现？",
        "priority": "high",
    },
    {
        "id": "check_03",
        "category": "dependency",
        "item": "是否与已有系统/数据模型存在冲突？冲突点是否已澄清？",
        "priority": "medium",
    },
    {
        "id": "check_04",
        "category": "requirement_clarity",
        "item": "验收标准是否可度量？关键场景是否已覆盖？",
        "priority": "medium",
    },
    {
        "id": "check_05",
        "category": "dependency",
        "item": "是否需要外部团队/第三方配合？排期是否已对齐？",
        "priority": "low",
    },
]


async def build_confirmation_checklist(
    draft: dict,
    feasibility: dict,
    conflicts: list[dict],
    call_llm=None,
) -> list[dict]:
    """Generate a confirmation checklist for the human reviewer.

    Uses LLM to generate contextual items; falls back to templates.
    """
    if call_llm is None:
        return _CHECKLIST_TEMPLATES

    title = draft.get("title", "")
    risk_level = feasibility.get("risk_level", "low")
    conflict_count = len(conflicts)
    conflict_desc = "\n".join(
        f"- {c.get('description', '')}" for c in (conflicts or [])[:3]
    ) or "无冲突"

    prompt = (
        f"需求: {title}\n风险等级: {risk_level}\n冲突({conflict_count}个):\n{conflict_desc}\n"
        "请生成3-5条产品经理审批时需要确认的检查项。返回 JSON 数组: "
        '[{"id":"check_01","category":"requirement_clarity|technical_risk|dependency",'
        '"item":"检查项描述","priority":"high|medium|low"}]'
    )

    try:
        llm_result = await call_llm(
            [{"role": "user", "content": prompt}],
            task_type="knowledge_analysis",
            req_id="",
            temperature=0.3,
            max_tokens=800,
        )
        if llm_result:
            items = json.loads(_extract_json_block(llm_result))
            if isinstance(items, list) and len(items) > 0:
                return items
    except Exception as e:
        logger.warning("Checklist LLM failed: %s", e)

    return _CHECKLIST_TEMPLATES


# ── Helpers ────────────────────────────────────────────────────────────────


def _extract_json_block(text: str) -> str:
    """Extract the first JSON object or array from an LLM response.

    Uses bracket-depth counting with string/escape tracking to correctly
    handle {'{' and '}' inside JSON string values (e.g. "当 {order.status} 变更时").
    """
    text = text.strip()
    # try raw parse first
    try:
        json.loads(text)
        return text
    except (json.JSONDecodeError, ValueError):
        pass
    # find first { or [
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start == -1:
            continue
        end_char = "}" if start_char == "{" else "]"
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            if escape:
                escape = False
                continue
            if text[i] == '\\' and in_string:
                escape = True
                continue
            if text[i] == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text
