"""LLM-based text compressor using DeepSeek API."""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class LLMCompressor:
    """Compress text using LLM (DeepSeek API or mock implementation)."""

    def __init__(self, api_key: Optional[str] = None, use_mock: bool = True):
        """Initialize LLM compressor.

        Args:
            api_key: DeepSeek API key (optional)
            use_mock: If True, use mock compression (simple truncation)
        """
        self.api_key = api_key
        self.use_mock = use_mock
        self.api_endpoint = "https://api.deepseek.com/v1/chat/completions"
        self.model = "deepseek-chat"

    async def compress(self, text: str, target_ratio: float = 0.5) -> str:
        """Compress text to target ratio while preserving key information.

        Args:
            text: Text to compress
            target_ratio: Target compression ratio (0.5 = 50% of original)

        Returns:
            Compressed text
        """
        if not text or len(text.strip()) == 0:
            return text

        if self.use_mock:
            return self._mock_compress(text, target_ratio)

        try:
            # Use DeepSeek API for real compression
            return await self._deepseek_compress(text, target_ratio)
        except Exception as e:
            logger.warning(f"LLM compression failed: {e}, falling back to mock")
            return self._mock_compress(text, target_ratio)

    def _mock_compress(self, text: str, target_ratio: float = 0.5) -> str:
        """Simple mock compression: truncate to target ratio.

        Preserves complete sentences when possible.

        Args:
            text: Text to compress
            target_ratio: Target compression ratio

        Returns:
            Compressed text (approximately target_ratio * len(text))
        """
        target_length = max(100, int(len(text) * target_ratio))

        if len(text) <= target_length:
            return text

        # Try to cut at sentence boundary
        truncated = text[:target_length]
        last_sentence_end = max(
            truncated.rfind('.'),
            truncated.rfind('!'),
            truncated.rfind('?'),
        )

        if last_sentence_end > target_length * 0.7:
            return truncated[:last_sentence_end + 1] + " [compressed]"

        return truncated + " [compressed]"

    async def _deepseek_compress(self, text: str, target_ratio: float = 0.5) -> str:
        """Call DeepSeek API to compress text.

        Args:
            text: Text to compress
            target_ratio: Target compression ratio

        Returns:
            Compressed text from API
        """
        if not self.api_key:
            logger.warning("No API key provided, using mock compression")
            return self._mock_compress(text, target_ratio)

        try:
            import httpx

            target_length = max(100, int(len(text) * target_ratio * 100))
            prompt = (
                f"Compress the following text to approximately {target_length} words "
                f"while preserving all key information, main logic, core functionality, "
                f"and critical decisions. Keep the compressed version concise but complete.\n\n"
                f"Original text:\n{text}"
            )

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": target_length + 50,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.api_endpoint,
                    json=payload,
                    headers=headers,
                )

                if response.status_code == 200:
                    result = response.json()
                    compressed = result["choices"][0]["message"]["content"].strip()
                    logger.info(
                        f"LLM compression: {len(text)} -> {len(compressed)} chars "
                        f"(ratio: {len(compressed) / len(text):.2%})"
                    )
                    return compressed
                else:
                    logger.error(f"DeepSeek API error: {response.status_code}")
                    return self._mock_compress(text, target_ratio)

        except Exception as e:
            logger.error(f"DeepSeek compression failed: {e}")
            return self._mock_compress(text, target_ratio)


async def compress_text_async(
    text: str, api_key: Optional[str] = None, use_mock: bool = True
) -> str:
    """Convenience function for async text compression.

    Args:
        text: Text to compress
        api_key: DeepSeek API key
        use_mock: Use mock compression

    Returns:
        Compressed text
    """
    compressor = LLMCompressor(api_key=api_key, use_mock=use_mock)
    return await compressor.compress(text)
