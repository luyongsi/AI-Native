"""Anthropic Adapter - Dev Agent primary provider.

Environment variable: ANTHROPIC_API_KEY
Default base_url: https://api.anthropic.com
Features: supports_vision=True, supports_embedding=False
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


class AnthropicAdapter(LLMAdapter):
    """Adapter for Anthropic Claude models.

    Used as the primary provider for dev_agent workflows.
    Supports text chat with streaming, and multimodal image understanding.
    """

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key=None,
        base_url=None,
        model=None,
        **kwargs,
    ):
        super().__init__(api_key=api_key, base_url=base_url, **kwargs)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.default_model = model or self.DEFAULT_MODEL
        self.features = ProviderFeatures(
            supports_vision=True,
            supports_embedding=False,
            supports_streaming=True,
            supports_function_calling=True,
            max_context_tokens=200000,
        )
        self._client = self._build_client()

    def _build_client(self):
        return httpx.Client(
            base_url=self.base_url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
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
        model = model or self.default_model
        system_prompt = None
        formatted_messages = self._convert_messages(messages)
        if formatted_messages and formatted_messages[0].get("role") == "system":
            system_prompt = formatted_messages[0]["content"]
            if isinstance(system_prompt, list):
                system_prompt = self._extract_text_from_content(system_prompt)
            formatted_messages = formatted_messages[1:]

        payload = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload.update(kwargs)
        if system_prompt:
            payload["system"] = system_prompt

        response = self._client.post("/v1/messages", json=payload)
        response.raise_for_status()
        data = response.json()

        content_blocks = data.get("content", [])
        text_content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")

        usage = data.get("usage", {})
        return LLMResponse(
            content=text_content,
            model=data.get("model", model),
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
            finish_reason=data.get("stop_reason", ""),
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
        system_prompt = None
        formatted_messages = self._convert_messages(messages)
        if formatted_messages and formatted_messages[0].get("role") == "system":
            system_prompt = formatted_messages[0]["content"]
            if isinstance(system_prompt, list):
                system_prompt = self._extract_text_from_content(system_prompt)
            formatted_messages = formatted_messages[1:]

        payload = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        payload.update(kwargs)
        if system_prompt:
            payload["system"] = system_prompt

        with self._client.stream("POST", "/v1/messages", json=payload) as response:
            response.raise_for_status()
            index = 0
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        content = delta.get("text", "")
                        if content:
                            yield LLMStreamChunk(
                                content=content,
                                finish_reason=None,
                                index=index,
                            )
                            index += 1
                elif event_type == "message_stop":
                    yield LLMStreamChunk(
                        content="",
                        finish_reason="stop",
                        index=index,
                    )

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
        """Multimodal image understanding via Anthropic Messages API."""
        model = model or self.default_model
        system_prompt = None
        formatted_messages = self._convert_messages(messages)
        if formatted_messages and formatted_messages[0].get("role") == "system":
            system_prompt = formatted_messages[0]["content"]
            if isinstance(system_prompt, list):
                system_prompt = self._extract_text_from_content(system_prompt)
            formatted_messages = formatted_messages[1:]

        payload = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload.update(kwargs)
        if system_prompt:
            payload["system"] = system_prompt

        response = self._client.post("/v1/messages", json=payload)
        response.raise_for_status()
        data = response.json()

        content_blocks = data.get("content", [])
        text_content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")

        usage = data.get("usage", {})
        return LLMResponse(
            content=text_content,
            model=data.get("model", model),
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
            finish_reason=data.get("stop_reason", ""),
            raw_response=data,
        )

    def embed(
        self,
        texts,
        model=None,
        **kwargs,
    ):
        raise NotImplementedError(
            "Anthropic does not support embeddings. "
            "Use an embedding-capable provider such as Qwen or Voyage."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _convert_messages(self, messages):
        """Convert OpenAI-format messages to Anthropic-format content blocks."""
        converted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, list):
                converted.append({"role": role, "content": content})
                continue

            if isinstance(content, str):
                converted.append({"role": role, "content": content})
                continue

            if isinstance(content, dict):
                if "image_url" in content:
                    img_url = content["image_url"].get("url", "")
                    converted.append({
                        "role": role,
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": self._infer_media_type(img_url),
                                    "data": self._extract_base64(img_url),
                                },
                            }
                        ],
                    })
                else:
                    converted.append({"role": role, "content": str(content)})
            else:
                converted.append({"role": role, "content": str(content)})

        return converted

    def _extract_text_from_content(self, content):
        """Extract plain text from an Anthropic content block list."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)
        return str(content)

    @staticmethod
    def _infer_media_type(url):
        """Infer media type from a data URL or file extension."""
        if url.startswith("data:") and ";" in url:
            return url.split(":")[1].split(";")[0]
        ext = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        mapping = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        return mapping.get(ext, "image/png")

    @staticmethod
    def _extract_base64(url):
        """Extract base64 data from a data URL or return the string as-is."""
        if url.startswith("data:") and "base64," in url:
            return url.split("base64,", 1)[1]
        return url
