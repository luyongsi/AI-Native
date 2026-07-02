"""Pipeline: main ContextBuilder orchestrating all stages."""

import logging
from typing import Dict, Any, List, Optional

from context_item import ContextItem, SelectResult
from embedder import Embedder, get_embedder
from selector import ContextSelector
from compress import ContextCompressor
from order import ContextOrderer
from isolate import ContextIsolate
from sanitize import ContextSanitizer

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Main pipeline: Query -> Select -> Order -> Compress -> Isolate -> Return.

    Usage:
        builder = ContextBuilder(db_config={...})
        result = builder.build_context(
            target_agent='A9',
            req_id='req-123',
            task_id='task-456',
            max_tokens=8000,
        )
    """

    def __init__(self,
                 db_config: Optional[dict] = None,
                 embedder: Optional[Embedder] = None,
                 selector: Optional[ContextSelector] = None,
                 orderer: Optional[ContextOrderer] = None,
                 compressor: Optional[ContextCompressor] = None,
                 isolator: Optional[ContextIsolate] = None,
                 sanitizer: Optional[ContextSanitizer] = None):
        """
        Args:
            db_config: PostgreSQL connection config
            embedder: Embedder instance (created if not provided)
            selector: ContextSelector (created if not provided)
            orderer: ContextOrderer (created if not provided)
            compressor: ContextCompressor (created if not provided)
            isolator: ContextIsolate (created if not provided)
            sanitizer: ContextSanitizer (created if not provided)
        """
        self.db_config = db_config or {}
        self.embedder = embedder or get_embedder()
        self.selector = selector or ContextSelector(db_config, self.embedder)
        self.orderer = orderer or ContextOrderer()
        self.compressor = compressor or ContextCompressor()
        self.isolator = isolator or ContextIsolate()
        self.sanitizer = sanitizer or ContextSanitizer()

    def build_context(self,
                      target_agent: str,
                      req_id: str = "",
                      task_id: str = "",
                      max_tokens: int = 8000,
                      query_text: str = "") -> Dict[str, Any]:
        """Execute the full context building pipeline.

        Args:
            target_agent: Agent ID (A1-A10)
            req_id: Request identifier
            task_id: Task identifier
            max_tokens: Token budget for context
            query_text: Optional free-text query

        Returns:
            Context package dict with items, metadata, and warnings.
        """
        pipeline_events = []
        fill_rate = 0.0
        items = []

        # --- Stage 0: Sanitize check ---
        if self.sanitizer.is_contaminated(target_agent):
            logger.warning(f"Agent {target_agent} context is contaminated, flushing...")
            self.sanitizer.flush_agent(target_agent)
            pipeline_events.append({
                'stage': 'sanitize',
                'action': 'flush',
                'agent': target_agent,
            })

        # --- Stage 1: Select ---
        try:
            result: SelectResult = self.selector.select(
                target_agent=target_agent,
                req_id=req_id,
                task_id=task_id,
                max_tokens=max_tokens,
                query_text=query_text,
            )
            items = result.items
            pipeline_events.append({
                'stage': 'select',
                'items_found': len(items),
                'tokens_used': result.tokens_used,
                'discarded': result.discarded,
            })
        except Exception as e:
            logger.error(f"Select stage failed: {e}")
            pipeline_events.append({
                'stage': 'select',
                'error': str(e),
            })
            # Record failure and return empty
            flush_needed = self.sanitizer.record_failure(target_agent)
            return self._build_response(
                target_agent=target_agent,
                items=[],
                pipeline_events=pipeline_events,
                max_tokens=max_tokens,
                fill_rate=0.0,
                contaminated=flush_needed,
                embedder=self.embedder,
            )

        # --- Stage 2: Order ---
        try:
            items = self.orderer.order(items, max_tokens=max_tokens)
            pos_summary = self.orderer.get_position_summary(items)
            pipeline_events.append({
                'stage': 'order',
                'positions': pos_summary,
            })
        except Exception as e:
            logger.error(f"Order stage failed: {e}")
            pipeline_events.append({
                'stage': 'order',
                'error': str(e),
            })
            # Continue with unordered items

        # --- Stage 3: Compress ---
        try:
            mid_items = [it for it in items if it.position == 'mid']
            if mid_items:
                items = self.compressor.compress(items, target_tokens=max_tokens)
                compressed_count = sum(1 for it in items if it.compressed)
                pipeline_events.append({
                    'stage': 'compress',
                    'mid_items': len(mid_items),
                    'compressed': compressed_count,
                })
            else:
                pipeline_events.append({
                    'stage': 'compress',
                    'mid_items': 0,
                    'compressed': 0,
                })
        except Exception as e:
            logger.error(f"Compress stage failed: {e}")
            pipeline_events.append({
                'stage': 'compress',
                'error': str(e),
            })

        # --- Stage 4: Isolate ---
        try:
            fill_rate = self.isolator.check(items, max_tokens)

            # Force compact if critical
            if fill_rate > self.isolator.critical_threshold:
                items = self.isolator.force_compact(items, max_tokens)
                fill_rate = self.isolator.check(items, max_tokens)
                pipeline_events.append({
                    'stage': 'isolate',
                    'action': 'force_compact',
                    'fill_rate': round(fill_rate, 3),
                })
            elif fill_rate > self.isolator.warning_threshold:
                pipeline_events.append({
                    'stage': 'isolate',
                    'action': 'warning',
                    'fill_rate': round(fill_rate, 3),
                })
            else:
                pipeline_events.append({
                    'stage': 'isolate',
                    'action': 'ok',
                    'fill_rate': round(fill_rate, 3),
                })
        except Exception as e:
            logger.error(f"Isolate stage failed: {e}")
            pipeline_events.append({
                'stage': 'isolate',
                'error': str(e),
            })

        # --- Stage 5: Sanitize (record success/failure) ---
        if fill_rate > 0.75:
            # High fill rate might indicate upstream issues
            self.sanitizer.record_failure(target_agent)
        else:
            self.sanitizer.record_success(target_agent)

        # Periodically clean stale sanitizer records
        self.sanitizer.cleanup_stale()

        return self._build_response(
            target_agent=target_agent,
            items=items,
            pipeline_events=pipeline_events,
            max_tokens=max_tokens,
            fill_rate=fill_rate,
            contaminated=self.sanitizer.is_contaminated(target_agent),
            embedder=self.embedder,
        )

    @staticmethod
    def _build_response(target_agent: str,
                        items: List[ContextItem],
                        pipeline_events: list,
                        max_tokens: int,
                        fill_rate: float,
                        contaminated: bool,
                        embedder: Optional[Embedder] = None) -> Dict[str, Any]:
        """Build the context_package response dict."""
        active_items = [it for it in items if it.position != 'discard']
        discarded_items = [it for it in items if it.position == 'discard']

        tokens_used = sum(it.tokens for it in active_items)
        tokens_discarded = sum(it.tokens for it in discarded_items)

        # Build structured output
        head_items = [it for it in active_items if it.position == 'head']
        mid_items = [it for it in active_items if it.position == 'mid']
        tail_items = [it for it in active_items if it.position == 'tail']

        def item_to_dict(it: ContextItem) -> dict:
            return {
                'type': it.type,
                'content': it.content,
                'relevance': round(it.relevance, 4),
                'position': it.position,
                'tokens': it.tokens,
                'file': it.file,
                'compressed': it.compressed,
            }

        # Determine embedding status
        embedding_status = "healthy"
        if embedder is not None and not embedder.remote_healthy:
            embedding_status = "degraded"

        context_package = {
            'target_agent': target_agent,
            'max_tokens': max_tokens,
            'tokens_used': tokens_used,
            'tokens_discarded': tokens_discarded,
            'fill_rate': round(fill_rate, 4),
            'contaminated': contaminated,
            'head': [item_to_dict(it) for it in head_items],
            'mid': [item_to_dict(it) for it in mid_items],
            'tail': [item_to_dict(it) for it in tail_items],
            'discarded': [item_to_dict(it) for it in discarded_items],
            'pipeline_events': pipeline_events,
            'meta': {
                'embedding_status': embedding_status,
                'pipeline_version': '1.0',
            },
        }

        return context_package

    def close(self):
        """Close connections."""
        if self.selector:
            self.selector.close()
