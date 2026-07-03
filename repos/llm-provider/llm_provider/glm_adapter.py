"""GLM-5V Adapter - ZhipuAI (BigModel) API.

Environment variable: GLM_API_KEY
Default base_url: https://open.bigmodel.cn/api/paas/v4
Features: supports_vision=True, supports_embedding=False

This adapter primarily serves as the fallback for vision tasks.
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


class GLMAdapter(LLMAdapter):
    """Adapter for GLM models via ZhipuAI BigModel API."""

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    DEFAULT_MODEL = "glm-4v-plus"

    def __init__(
        self,
        api_key=None,
        base_url=None,
        model=None,
        **kwargs,
    ):
        super().__init__(api_key=api_key, base_url=base_url, **kwargs)
        self.api_key = api_key or os.environ.get("GLM_API_KEY", "")
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.default_model = model or self.DEFAULT_MODEL
        self.features = ProviderFeatures(
            supports_vision=True,
            supports_embedding=False,
            supports_streaming=True,
            supports_function_calling=False,
            max_context_tokens=128000,
        )
        self._client = self._build_client()

    def _build_client(self):
        return httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": "Bearer {}".format(self.api_key),
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(120.0),
        )

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

        response = self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
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

        with self._client.stream("POST", "/chat/completions", json=payload) as response:
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
        """Multimodal image understanding via GLM-4V.

        Reuses the chat endpoint; the ZhipuAI API handles vision messages
        through the standard /chat/completions path when a vision-capable
        model is selected.
        """
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        payload.update(kwargs)

        response = self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", model),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", ""),
            raw_response=data,
        )

    def embed(
        self,
        texts,
        model=None,
        **kwargs,
    ):
        raise NotImplementedError(
            "GLM does not support embeddings. "
            "Use an embedding-capable provider such as Qwen or Voyage."
        )
