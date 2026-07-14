"""MC Backend — SSE Event Formatter.

Shared utility for formatting Server-Sent Events.
Used by A1 (requirement analysis) and A3 (prototype generation).
"""

import json


def format_sse_event(event_type: str, data: dict | str) -> str:
    """Format a dict or string as an SSE event string.

    Args:
        event_type: The event name (e.g. 'thinking', 'prototype_update', 'done').
        data: Event payload — dict is JSON-serialized, str is used as-is.

    Returns:
        An SSE-formatted string: "event: {type}\\ndata: {payload}\\n\\n"

    Example:
        >>> format_sse_event('thinking', {'message': '分析中...'})
        'event: thinking\\ndata: {"message": "分析中..."}\\n\\n'
    """
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def format_sse_error(message: str) -> str:
    """Shortcut for formatting an error SSE event."""
    return format_sse_event("error", {"message": message})


def format_sse_done(payload: dict | None = None) -> str:
    """Shortcut for formatting a done SSE event."""
    return format_sse_event("done", payload or {})
