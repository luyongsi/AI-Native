"""Context sanitizer - strip or truncate context to fit token limits."""

MAX_CONTEXT_CHARS = 128_000  # safe upper bound


def sanitize_context(context: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Return *context* trimmed to *max_chars*.

    When the context exceeds the limit the middle portion is replaced
    with a truncation marker so both preamble and conclusion are preserved.
    """
    if len(context) <= max_chars:
        return context

    marker = "\n\n... [context truncated] ...\n\n"
    half = (max_chars - len(marker)) // 2
    return context[:half] + marker + context[-half:]
