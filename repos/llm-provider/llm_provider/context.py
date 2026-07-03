"""LLMCallContext — metadata passed from Agent to audit layer."""

from dataclasses import dataclass, field


@dataclass
class LLMCallContext:
    """Contextual metadata for a single LLM call.

    Passed by BaseAgentWorker.call_llm() to LLMProviderManager and
    forwarded to the auditor for tracing and cost attribution.
    """

    agent_id: str = ""
    req_id: str = ""
    workflow_id: str = ""
    task_type: str = "text"
