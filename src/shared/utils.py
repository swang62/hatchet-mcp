"""General shared utilities."""

MAX_LENGTH_OUTPUT = 300


def trunc(text: str) -> str:
    """Truncate text to maxlen chars, appending '...' if truncated."""
    if len(text) <= MAX_LENGTH_OUTPUT:
        return text
    return text[:MAX_LENGTH_OUTPUT] + "..."
