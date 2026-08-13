"""Decide which channel a job belongs to.

Deliberately rule-based rather than LLM-driven: routing must be free, instant,
and identical for the same input every time. It also works retroactively on
jobs that were enriched before routing existed.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .settings import load_profile

INDIA = "india"
INTERNATIONAL = "international"


@lru_cache(maxsize=1)
def india_patterns() -> tuple[str, ...]:
    routing = load_profile().get("routing", {})
    return tuple(p.strip().lower() for p in routing.get("india_location_patterns", []) if p)


@lru_cache(maxsize=1)
def _python_regex() -> re.Pattern[str]:
    """Word-boundary match, so 'Indianapolis' does not read as 'India'."""
    alternation = "|".join(re.escape(p) for p in india_patterns())
    return re.compile(rf"\b({alternation})\b", re.IGNORECASE)


@lru_cache(maxsize=1)
def postgres_regex() -> str:
    r"""Same pattern for Postgres `~*`.

    Postgres spells the word boundary `\y`, not `\b` — `\b` means backspace
    inside a Postgres regex and would silently match nothing.
    """
    alternation = "|".join(re.escape(p) for p in india_patterns())
    return rf"\y({alternation})\y"


def is_india(location: str | None) -> bool:
    if not location:
        return False
    return bool(_python_regex().search(location))


def route_of(location: str | None) -> str:
    """Every job belongs to exactly one channel."""
    return INDIA if is_india(location) else INTERNATIONAL


@lru_cache(maxsize=1)
def configured_routes() -> tuple[str, ...]:
    """Route names in publishing order, from profile.yaml."""
    routing = load_profile().get("routing", {})
    return tuple((routing.get("channels") or {}).keys())
