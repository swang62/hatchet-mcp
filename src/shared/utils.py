"""General shared utilities."""

from src.shared.constants import LOG_OUTPUT_MAX


def trunc(text: str, maxlen: int = LOG_OUTPUT_MAX) -> str:
    """Truncate text to maxlen chars, appending '...' if truncated."""
    if len(text) <= maxlen:
        return text
    return text[:maxlen] + "..."
