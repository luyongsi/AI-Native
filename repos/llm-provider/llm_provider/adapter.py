"""LLM Provider Abstraction Layer - Abstract Base Classes and Data Models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""
    raw_response: Any = None
    call_id: str = ""


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming LLM response."""

    content: str
    finish_reason: Optional[str] = None
    index: int = 0


@dataclass
class EmbeddingResponse:
    """Standardized embedding response."""

    embedding: List[float]
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)


@dataclass
class ProviderFeatures:
    """Declares what capabilities a provider supports."""

    supports_vision: bool = False
    supports_embedding: bool = False
    supports_streaming: bool = True
    supports_function_calling: bool = False
    max_context_tokens: int = 8192


class LLMAdapter(ABC):
    """Abstract base class for all LLM provider adapters.

    All concrete adapters MUST implement: chat(), chat_stream(),
    image_understand(), and embed().
    """

    def __init__(self, api_key=None, base_url=None, **kwargs):
        self.api_key = api_key
        self.base_url = base_url
        self.features = ProviderFeatures()
        self._client = None

    @property
    def provider_name(self):
        return self.__class__.__name__

    @abstractmethod
    def chat(self, messages, model=None, temperature=0.7, max_tokens=4096, **kwargs):
        """Send a chat completion request and return a full response."""
        ...

    @abstractmethod
    def chat_stream(self, messages, model=None, temperature=0.7, max_tokens=4096, **kwargs):
        """Send a chat completion request and yield streaming chunks."""
        ...

    @abstractmethod
    def image_understand(self, messages, model=None, temperature=0.7, max_tokens=4096, **kwargs):
        """Send a multimodal (image + text) request and return a full response."""
        ...

    @abstractmethod
    def embed(self, texts, model=None, **kwargs):
        """Generate embeddings for the given texts."""
        ...

    def _build_client(self):
        """Build and cache the HTTP client. Override in subclasses."""
        return None

    def _chat_with_audit(self, messages, ctx=None, **kwargs):
        """Synchronous chat with audit logging.

        Called by LLMProviderManager when an auditor is configured.
        ctx must be an LLMCallContext (or object with agent_id, req_id,
        workflow_id, task_type attributes).
        """
        from .audit import get_auditor

        auditor = get_auditor()
        ctx = ctx or _EMPTY_CTX

        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)

        call_id = auditor.record_start(
            agent_id=getattr(ctx, "agent_id", ""),
            req_id=getattr(ctx, "req_id", ""),
            workflow_id=getattr(ctx, "workflow_id", ""),
            task_type=getattr(ctx, "task_type", "text"),
            provider=self.provider_name,
            model=kwargs.get("model") or getattr(self, "default_model", ""),
            prompt_chars=prompt_chars,
        )

        import time
        started = time.monotonic()
        try:
            response = self.chat(messages=messages, **kwargs)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            usage = response.usage if hasattr(response, "usage") else {}
            auditor.record_end(
                call_id,
                response_chars=len(response.content or ""),
                response_preview=(response.content or "")[:200],
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                duration_ms=elapsed_ms,
            )
            response.call_id = call_id
            return response
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            auditor.record_end(call_id, duration_ms=elapsed_ms, error=exc)
            raise


# Sentinel for when ctx is not provided
class _EmptyCtx:
    agent_id = ""
    req_id = ""
    workflow_id = ""
    task_type = "text"


_EMPTY_CTX = _EmptyCtx()
