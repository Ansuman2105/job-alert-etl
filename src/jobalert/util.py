"""Small shared helpers."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]*\n[ \t]*")
_BLANKS = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str | None:
    """Turn an HTML job description into readable plain text.

    Job descriptions arrive as HTML on most ATS boards. The LLM reads this and
    so does the Telegram message, and neither wants markup.
    """
    if not raw:
        return None
    text = raw.replace("</p>", "\n\n").replace("<br>", "\n").replace("<br/>", "\n")
    text = text.replace("<br />", "\n").replace("</li>", "\n").replace("<li>", "- ")
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _WS.sub("\n", text)
    text = _BLANKS.sub("\n\n", text)
    return text.strip() or None


def parse_dt(value: object) -> datetime | None:
    """Parse the several date shapes these feeds use.

    Handles ISO 8601 (with or without Z), epoch seconds, and epoch milliseconds.
    Returns tz-aware UTC, or None when the value is unusable — a bad date should
    never fail a whole batch.
    """
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        # Anything past ~2001 in seconds is > 1e9; ms values are ~1e12.
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return parse_dt(int(text))
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    return None


def truncate(text: str | None, limit: int) -> str | None:
    """Cut to `limit` characters on a word boundary where possible."""
    if not text or len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip() + "..."
