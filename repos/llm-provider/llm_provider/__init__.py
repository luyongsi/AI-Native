"""LLM Provider Abstraction Layer.

Unified interface for multiple LLM providers with intelligent routing.
"""

from .adapter import (
    EmbeddingResponse,
    LLMAdapter,
    LLMResponse,
    LLMStreamChunk,
    ProviderFeatures,
)
from .audit import LLMAuditor, get_auditor
from .context import LLMCallContext
from .manager import LLMProviderManager
from .deepseek_adapter import DeepSeekAdapter
from .qwen_adapter import QwenAdapter
from .glm_adapter import GLMAdapter
from .anthropic_adapter import AnthropicAdapter

__all__ = [
    "LLMAdapter",
    "LLMResponse",
    "LLMStreamChunk",
    "EmbeddingResponse",
    "ProviderFeatures",
    "LLMCallContext",
    "LLMAuditor",
    "get_auditor",
    "LLMProviderManager",
    "DeepSeekAdapter",
    "QwenAdapter",
    "GLMAdapter",
    "AnthropicAdapter",
]

__version__ = "0.1.0"
