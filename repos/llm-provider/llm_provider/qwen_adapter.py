"""Qwen Adapter - DashScope compatible-mode API.

Environment variable: QWEN_API_KEY  (DashScope API key)
Default base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
Features: supports_vision=True, supports_embedding=True
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


class QwenAdapter(LLMAdapter):
    """Adapter for Qwen models via DashScope compatible-mode API.

    Supports:
        - Text chat: models like qwen-plus, qwen-max
        - Vision / multimodal: models like qwen-vl-plus, qwen-vl-max
        - Embeddings: models like text-embedding-v3
    """

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DEFAULT_CHAT_MODEL = "qwen-plus"
    DEFAULT_VISION_MODEL = "qwen-vl-plus"
    DEFAULT_EMBED_MODEL = "text-embedding-v3"

    def __init__(
        self,
        api_key=None,
        base_url=None,
        chat_model=None,
        vision_model=None,
        embed_model=None,
        **kwargs,
    ):
        super().__init__(api_key=api_key, base_url=base_url, **kwargs)
        self.api_key = api_key or os.environ.get("QWEN_API_KEY", "")
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.chat_model = chat_model or self.DEFAULT_CHAT_MODEL
        self.vision_model = vision_model or self.DEFAULT_VISION_MODEL
        self.embed_model = embed_model or self.DEFAULT_EMBED_MODEL
        self.features = ProviderFeatures(
            supports_vision=True,
            supports_embedding=True,
            supports_streaming=True,
            supports_function_calling=False,
            max_context_tokens=32768,
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

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        **kwargs,
    ):
        model = model or self.chat_model
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
        model = model or self.chat_model
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

    # ------------------------------------------------------------------
    # Vision / Multimodal
    # ------------------------------------------------------------------

    def image_understand(
        self,
        messages,
        model=None,
        temperature=0.7,
        max_tokens=4096,
        **kwargs,
    ):
        model = model or self.vision_model
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

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed(
        self,
        texts,
        model=None,
        **kwargs,
    ):
        model = model or self.embed_model
        payload = {
            "model": model,
            "input": texts,
        }
        payload.update(kwargs)

        response = self._client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("data", []):
            results.append(
                EmbeddingResponse(
                    embedding=item["embedding"],
                    model=data.get("model", model),
                    usage=data.get("usage", {}),
                )
            )
        return results
