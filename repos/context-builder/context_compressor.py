"""Enhanced context compressor with LLM, code, and deduplication support."""

import asyncio
import logging
import time
from typing import List, Dict, Optional, Tuple

from context_item import ContextItem
from compressors.llm_compressor import LLMCompressor
from compressors.code_compressor import CodeCompressor
from compressors.deduplication import Deduplicator, count_tokens
from compressors.metrics import CompressionMetrics

logger = logging.getLogger(__name__)


class ContextCompressorV2:
    """Advanced context compressor with multi-strategy compression.

    Stages:
    1. Detect content type (code vs knowledge)
    2. Apply type-specific compression (CodeCompressor or LLMCompressor)
    3. Deduplicate similar content
    4. Record metrics and token counts
    """

    # File extensions treated as code
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java',
        '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.php', '.swift',
        '.kt', '.scala', '.r', '.sql', '.sh', '.bash', '.ps1',
    }

    def __init__(
        self,
        llm_api_key: Optional[str] = None,
        use_mock_llm: bool = True,
        similarity_threshold: float = 0.90,
    ):
        """Initialize advanced context compressor.

        Args:
            llm_api_key: DeepSeek API key (optional)
            use_mock_llm: Use mock LLM compression (simple truncation)
            similarity_threshold: Dedup threshold (0.0-1.0)
        """
        self.llm_compressor = LLMCompressor(api_key=llm_api_key, use_mock=use_mock_llm)
        self.code_compressor = CodeCompressor()
        self.deduplicator = Deduplicator(similarity_threshold=similarity_threshold)
        self.metrics = CompressionMetrics()

    @staticmethod
    def _is_code(item: ContextItem) -> bool:
        """Check if item is code.

        Args:
            item: Context item

        Returns:
            True if item appears to be code
        """
        if item.type == 'code':
            return True

        # Check file extension
        if item.file:
            ext = '.' + item.file.rsplit('.', 1)[-1] if '.' in item.file else ''
            return ext.lower() in ContextCompressorV2.CODE_EXTENSIONS

        return False

    def _get_language(self, file_path: Optional[str]) -> str:
        """Detect programming language from file extension.

        Args:
            file_path: File path or name

        Returns:
            Programming language name
        """
        if not file_path:
            return 'python'

        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.c': 'c',
            '.cpp': 'cpp',
            '.cs': 'cs',
            '.rb': 'ruby',
            '.php': 'php',
            '.sh': 'shell',
            '.bash': 'bash',
        }

        ext = '.' + file_path.rsplit('.', 1)[-1] if '.' in file_path else ''
        return ext_map.get(ext.lower(), 'python')

    async def compress_candidates_async(
        self,
        candidates: List[Dict],
        target_compression_ratio: float = 0.5,
    ) -> Tuple[List[Dict], Dict]:
        """Compress candidates using async compression.

        Args:
            candidates: List of candidate dictionaries with 'content', 'type', etc.
            target_compression_ratio: Target ratio (0.5 = 50% of original)

        Returns:
            (compressed_candidates, metrics_dict)
        """
        start_time = time.time()
        compressed = []
        original_tokens = 0
        compressed_tokens = 0

        try:
            for candidate in candidates:
                content = candidate.get('content', '')
                content_type = candidate.get('content_type', candidate.get('type', 'knowledge'))
                original_token_count = count_tokens(content)
                original_tokens += original_token_count

                # Compress based on type
                if content_type == 'code':
                    language = self._get_language(candidate.get('file'))
                    try:
                        compressed_content = self.code_compressor.compress(content, language)
                        self.metrics.record_compression(
                            original_token_count,
                            count_tokens(compressed_content),
                            0,  # Duration handled separately
                            compress_type='code',
                        )
                    except Exception as e:
                        logger.error(f"Code compression failed: {e}")
                        self.metrics.record_error(f"Code compression: {e}")
                        compressed_content = content
                else:
                    # Use LLM for knowledge/doc items
                    try:
                        compressed_content = await self.llm_compressor.compress(
                            content,
                            target_ratio=target_compression_ratio,
                        )
                        self.metrics.record_compression(
                            original_token_count,
                            count_tokens(compressed_content),
                            0,
                            compress_type='llm',
                        )
                    except Exception as e:
                        logger.error(f"LLM compression failed: {e}")
                        self.metrics.record_error(f"LLM compression: {e}")
                        compressed_content = content

                # Update candidate
                candidate['content'] = compressed_content
                candidate['token_count'] = count_tokens(compressed_content)
                candidate['original_token_count'] = original_token_count
                candidate['compressed'] = True
                compressed.append(candidate)
                compressed_tokens += candidate['token_count']

            # Deduplication phase
            deduped = self.deduplicator.deduplicate(compressed)
            self.metrics.record_deduplication(len(compressed), len(deduped))

            # Record overall metrics
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.compress_duration_ms = duration_ms

            if original_tokens > 0:
                final_tokens = sum(c.get('token_count', 0) for c in deduped)
                compression_ratio = final_tokens / original_tokens
                self.metrics.compress_ratio = compression_ratio

                logger.info(
                    f"COMPRESS stage complete: "
                    f"{len(candidates)} candidates -> {len(deduped)} after dedup, "
                    f"{original_tokens} -> {final_tokens} tokens "
                    f"(ratio: {compression_ratio:.2%}), "
                    f"duration: {duration_ms:.1f}ms"
                )

            return deduped, self.metrics.to_dict()

        except Exception as e:
            logger.error(f"Async compression failed: {e}")
            self.metrics.record_error(f"Async compression: {e}")
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.compress_duration_ms = duration_ms
            return candidates, self.metrics.to_dict()

    def compress_candidates(
        self,
        candidates: List[Dict],
        target_compression_ratio: float = 0.5,
    ) -> Tuple[List[Dict], Dict]:
        """Synchronous wrapper for compress_candidates_async.

        Args:
            candidates: List of candidate dictionaries
            target_compression_ratio: Target compression ratio

        Returns:
            (compressed_candidates, metrics_dict)
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.compress_candidates_async(candidates, target_compression_ratio)
            )
        finally:
            loop.close()

    def compress_context_items(
        self,
        items: List[ContextItem],
        target_tokens: int = 0,
    ) -> List[ContextItem]:
        """Compress ContextItem objects (for integration with existing pipeline).

        Args:
            items: List of ContextItem objects
            target_tokens: Optional token budget

        Returns:
            Compressed ContextItem list
        """
        start_time = time.time()

        try:
            for item in items:
                if item.position in ('head', 'tail'):
                    # Preserve head and tail items
                    continue

                if item.position == 'discard':
                    continue

                original_content = item.content
                original_tokens = count_tokens(original_content)

                # Compress based on type
                if self._is_code(item):
                    language = self._get_language(item.file)
                    compressed_content = self.code_compressor.compress(
                        original_content,
                        language,
                    )
                    item.tokens = count_tokens(compressed_content)
                    item.compressed = True
                    self.metrics.record_compression(
                        original_tokens,
                        item.tokens,
                        0,
                        compress_type='code',
                    )

                elif item.type in ('knowledge', 'doc'):
                    # For synchronous context items, use mock compression
                    # (to avoid async complexity in existing code)
                    if len(original_content) > 2000:
                        # Simple truncation to 60%
                        compressed_content = original_content[:int(len(original_content) * 0.6)]
                        compressed_content += '\n[compressed]'
                        item.content = compressed_content
                        item.tokens = count_tokens(compressed_content)
                        item.compressed = True
                        self.metrics.record_compression(
                            original_tokens,
                            item.tokens,
                            0,
                            compress_type='knowledge',
                        )

            # Record metrics
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.compress_duration_ms = duration_ms

            logger.info(
                f"Context items compression: {len(items)} items, "
                f"duration: {duration_ms:.1f}ms"
            )

            return items

        except Exception as e:
            logger.error(f"Context items compression failed: {e}")
            self.metrics.record_error(f"Context items: {e}")
            return items

    def get_metrics(self) -> Dict:
        """Get compression metrics.

        Returns:
            Metrics dictionary
        """
        return self.metrics.to_dict()

    def reset_metrics(self):
        """Reset metrics."""
        self.metrics.reset()
