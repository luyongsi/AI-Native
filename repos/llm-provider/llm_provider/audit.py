"""LLMAuditor — centralized, thread-safe LLM call audit logging.

Module-level singleton (get_auditor) ensures all agents share one auditor
with a single Lock for JSONL file writes, preventing interleaved lines.

Outputs: file (JSONL) + stdout (one-line summary).
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_auditor_instance: "LLMAuditor | None" = None
_auditor_lock = threading.Lock()

MAX_PENDING = 1000  # hard cap to prevent memory leaks


def get_auditor(outputs=None) -> "LLMAuditor":
    """Return the module-level singleton LLMAuditor (thread-safe)."""
    global _auditor_instance
    if _auditor_instance is None:
        with _auditor_lock:
            if _auditor_instance is None:
                _auditor_instance = LLMAuditor(outputs=outputs)
    return _auditor_instance


class LLMAuditor:
    """Centralized LLM call auditor.

    Usage (from adapter._chat_with_audit):
        auditor = get_auditor(outputs=["file", "stdout"])
        call_id = auditor.record_start(agent_id="A1", req_id="xxx", ...)
        try:
            response = adapter.chat(messages, ...)
            auditor.record_end(call_id, response_chars=..., ...)
        except Exception as e:
            auditor.record_end(call_id, response_chars=0, ..., error=e)
    """

    def __init__(self, outputs=None):
        self.outputs = outputs or ["file", "stdout"]
        self._lock = threading.Lock()
        self._log_path = Path(os.environ.get(
            "LLM_AUDIT_LOG", "/opt/ai-native/logs/llm_audit.jsonl"
        ))
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._pending: dict[str, dict] = {}

    # ── public API ──────────────────────────────────────────────────

    def record_start(
        self,
        agent_id: str,
        req_id: str = "",
        workflow_id: str = "",
        task_type: str = "text",
        provider: str = "",
        model: str = "",
        prompt_chars: int = 0,
    ) -> str:
        """Record the start of an LLM call. Returns a call_id for record_end."""
        call_id = str(uuid4())
        record = {
            "call_id": call_id,
            "agent_id": agent_id,
            "req_id": req_id or "UNKNOWN",
            "workflow_id": workflow_id,
            "task_type": task_type,
            "provider": provider,
            "model": model,
            "prompt_chars": prompt_chars,
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if len(self._pending) >= MAX_PENDING:
                oldest = next(iter(self._pending))
                logger.warning(
                    "Auditor pending overflow (%d), dropping call_id=%s",
                    MAX_PENDING, oldest,
                )
                del self._pending[oldest]
            self._pending[call_id] = record
        return call_id

    def record_end(
        self,
        call_id: str,
        response_chars: int = 0,
        response_preview: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
        error: Exception | None = None,
    ):
        """Record the completion of an LLM call."""
        with self._lock:
            record = self._pending.pop(call_id, {})
        if not record:
            logger.warning("Auditor: call_id=%s not found in pending", call_id[:12])
            return

        record.update({
            "status": "error" if error else "success",
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "response_chars": response_chars,
            "response_preview": (response_preview or "")[:500],
            "error_type": type(error).__name__ if error else None,
            "error_message": str(error)[:500] if error else None,
        })
        self._write(record)

    # ── internal ────────────────────────────────────────────────────

    def _write(self, record: dict):
        line = json.dumps(record, ensure_ascii=False)
        if "file" in self.outputs:
            with self._lock:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        if "stdout" in self.outputs:
            status_icon = "X" if record.get("status") == "error" else "OK"
            tokens = record.get("total_tokens", 0)
            dur = (record.get("duration_ms", 0) or 0) / 1000
            req_short = (record.get("req_id", "") or "")[:8]
            print(
                f"[LLM] {record.get('agent_id', '?')} | "
                f"task={record.get('task_type', '?')} | "
                f"req={req_short} | "
                f"{record.get('prompt_chars', 0)}->{record.get('response_chars', 0)} chars | "
                f"{dur:.1f}s | tokens={tokens} | {status_icon}"
            )
