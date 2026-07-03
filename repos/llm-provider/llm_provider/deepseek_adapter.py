"""DeepSeek Adapter - OpenAI-compatible endpoint.

Environment variable: DEEPSEEK_API_KEY
Default base_url: https://api.deepseek.com
Features: supports_vision=False, supports_embedding=False
"""

import json
import os
from typing import Any, Dict, Iterator, List, Optional

import httpx

from .adapter import (
    EmbeddingResponse,
    LLMAdapter,
    LLMResponse,
    LLMStreamChunk,
    ProviderFeatures,
)


class DeepSeekAdapter(LLMAdapter):
    """Adapter for DeepSeek API (OpenAI-compatible)."""

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key=None,
        base_url=None,
        model=None,
        **kwargs,
    ):
        super().__init__(api_key=api_key, base_url=base_url, **kwargs)
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.default_model = model or self.DEFAULT_MODEL
        self.features = ProviderFeatures(
            supports_vision=False,
            supports_embedding=False,
            supports_streaming=True,
            supports_function_calling=False,
            max_context_tokens=65536,
        )
        self._client = self._build_client()

    def _build_client(self):
        return httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": "Bearer {}".format(self.api_key or os.environ.get("DEEPSEEK_API_KEY", "")),
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(120.0),
        )

    def _ensure_client(self):
        """Rebuild client if api_key changed (lazy init)."""
        api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key and (self._client is None or "Bearer " not in str(self._client.headers.get("authorization", ""))):
            self.api_key = api_key
            self._client = self._build_client()
        return self._client

    def chat(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        **kwargs,
    ):
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        payload.update(kwargs)

        client = self._ensure_client()
        response = client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content", "") or message.get("reasoning_content", "") or ""
        return LLMResponse(
            content=content,
            model=data.get("model", model),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", ""),
            raw_response=data,
        )

    def chat_stream(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        **kwargs,
    ):
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        payload.update(kwargs)

        with self._client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            index = 0
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk_data = json.loads(data_str)
                    delta = chunk_data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    finish = chunk_data["choices"][0].get("finish_reason")
                    if content:
                        yield LLMStreamChunk(
                            content=content,
                            finish_reason=finish,
                            index=index,
                        )
                        index += 1
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    def image_understand(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        **kwargs,
    ):
        raise NotImplementedError(
            "DeepSeek does not support vision/image_understand. "
            "Use a multimodal-capable provider such as Qwen or GLM."
        )

    def embed(
        self,
        texts,
        model=None,
        **kwargs,
    ):
        raise NotImplementedError(
            "DeepSeek does not support embeddings. "
            "Use an embedding-capable provider such as Qwen or Voyage."
        )
