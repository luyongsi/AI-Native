"""LLMProviderManager - Routes requests to the appropriate provider adapter."""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .adapter import (
    EmbeddingResponse,
    LLMAdapter,
    LLMResponse,
    LLMStreamChunk,
)


class LLMProviderManager:
    """Central manager that routes LLM tasks to the best-fit provider.

    Routing logic:
        text       -> primary (default: deepseek)
        vision     -> multimodal (default: qwen) -> fallback to glm
        embedding  -> embedding provider (default: qwen) -> fallback to voyage
        dev_agent  -> dev_agent provider (default: anthropic)
    """

    def __init__(
        self,
        adapters=None,
        default_routes=None,
        fallback_chains=None,
        auditor=None,
    ):
        self._adapters = adapters or {}
        self._default_routes = default_routes or {
            "text": "deepseek",
            "vision": "qwen",
            "embedding": "qwen",
            "dev_agent": "anthropic",
        }
        self._fallback_chains = fallback_chains or {
            "vision": ["qwen"],
        }
        self._auditor = auditor

    def register(self, name, adapter):
        """Register a provider adapter by name."""
        self._adapters[name] = adapter

    def unregister(self, name):
        """Remove a registered provider."""
        self._adapters.pop(name, None)

    @property
    def registered_providers(self):
        return list(self._adapters.keys())

    def chat(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        task_type="text",
        provider=None,
        ctx=None,
        **kwargs,
    ):
        """Execute a chat completion, routing by task_type.

        If ctx (LLMCallContext) and auditor are configured, the adapter's
        _chat_with_audit is used for automatic start/end audit logging.
        """
        adapter_name = provider or self._route(task_type)
        return self._execute_with_fallback(
            adapter_name,
            task_type,
            "chat",
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            ctx=ctx,
            **kwargs,
        )

    def chat_stream(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        task_type="text",
        provider=None,
        **kwargs,
    ):
        """Stream a chat completion, routing by task_type."""
        adapter_name = provider or self._route(task_type)
        adapter = self._get_adapter(adapter_name)
        return adapter.chat_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    def image_understand(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        provider=None,
        **kwargs,
    ):
        """Execute a multimodal image understanding request."""
        adapter_name = provider or self._route("vision")
        return self._execute_with_fallback(
            adapter_name,
            "vision",
            "image_understand",
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    def embed(
        self,
        texts,
        model=None,
        provider=None,
        **kwargs,
    ):
        """Generate embeddings, routing by embedding task_type."""
        adapter_name = provider or self._route("embedding")
        return self._execute_with_fallback(
            adapter_name,
            "embedding",
            "embed",
            texts=texts,
            model=model,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    def _route(self, task_type):
        """Look up the primary provider for the given task type."""
        adapter_name = self._default_routes.get(task_type)
        if adapter_name is None:
            raise ValueError(
                "No default route configured for task_type='{}'. "
                "Known types: {}".format(task_type, list(self._default_routes.keys()))
            )
        if adapter_name not in self._adapters:
            raise RuntimeError(
                "Default provider '{}' for task_type='{}' "
                "is not registered. Registered: {}".format(
                    adapter_name, task_type, list(self._adapters.keys())
                )
            )
        return adapter_name

    def _get_fallback(self, task_type):
        """Return the fallback provider chain for a task type."""
        return self._fallback_chains.get(task_type, [])

    def _get_adapter(self, name):
        """Return a registered adapter by name, or raise."""
        adapter = self._adapters.get(name)
        if adapter is None:
            raise RuntimeError(
                "Provider '{}' is not registered. "
                "Registered: {}".format(name, list(self._adapters.keys()))
            )
        return adapter

    def _execute_with_fallback(self, primary, task_type, method, **kwargs):
        """Try primary adapter, falling back through the chain on failure.

        When method='chat' and ctx is provided with an auditor configured,
        uses adapter._chat_with_audit for automatic audit logging.
        """
        last_error = None
        chain = [primary] + self._get_fallback(task_type)
        ctx = kwargs.pop("ctx", None)

        for name in chain:
            adapter = self._get_adapter(name)
            try:
                if method == "chat" and ctx is not None and self._auditor is not None:
                    return adapter._chat_with_audit(ctx=ctx, **kwargs)
                func = getattr(adapter, method)
                return func(**kwargs)
            except Exception as exc:
                last_error = exc
                continue

        raise RuntimeError(
            "All providers in chain {} failed for task_type='{}'. "
            "Last error: {}".format(chain, task_type, last_error)
        ) from last_error
