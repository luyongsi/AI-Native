"""ContextItem and SelectResult dataclasses for Context Builder."""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ContextItem:
    """A single context item (code chunk, knowledge snippet, spec, etc.)."""
    type: str            # 'code', 'knowledge', 'spec', 'prototype', 'log', 'doc'
    content: str         # The actual text content
    relevance: float     # 0.0 - 1.0 relevance score from retrieval
    position: str        # 'head', 'mid', 'tail', 'discard'
    tokens: int          # Estimated token count
    file: Optional[str] = None   # Source file path
    compressed: bool = False     # Whether content has been compressed

    def __repr__(self) -> str:
        preview = self.content[:60].replace('\n', ' ') + ('...' if len(self.content) > 60 else '')
        return (f"ContextItem(type={self.type}, relevance={self.relevance:.3f}, "
                f"position={self.position}, tokens={self.tokens}, "
                f"file={self.file}, compressed={self.compressed}, "
                f"content='{preview}')")


@dataclass
class SelectResult:
    """Result from the ContextSelector stage."""
    items: List[ContextItem] = field(default_factory=list)
    tokens_used: int = 0
    discarded: int = 0

    @property
    def total_tokens(self) -> int:
        return self.tokens_used + self.discarded
