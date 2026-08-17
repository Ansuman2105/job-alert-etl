"""Provider-agnostic LLM interface and response parsing."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from ..models import JobFacts

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMError(RuntimeError):
    """The provider failed or returned something unusable."""


class LLMClient(ABC):
    """Every provider implements exactly this."""

    name: str
    model: str

    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        """Return the model's reply parsed as a JSON object."""

    def preflight(self) -> None:
        """Check the configured model exists before processing a batch.

        Optional: a provider without a catalogue endpoint keeps the default
        no-op and simply fails on the first real call.
        """
        return None


def extract_json(text: str) -> dict:
    """Parse a JSON object out of a model reply.

    Small models sometimes wrap JSON in prose or a markdown fence even when
    asked not to, so fall back to locating the outermost braces before giving up.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK.search(text)
    if not match:
        raise LLMError(f"no JSON object in reply: {text[:200]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"malformed JSON in reply: {text[:200]!r}") from exc


def _clean_list(value: object, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(v).strip() for v in value if str(v).strip()]
    return out[:limit]


def _clean_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d.]", "", value)
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return None


def _clean_int(value: object) -> int | None:
    number = _clean_number(value)
    return int(number) if number is not None else None


def parse_facts(payload: dict, allowed_families: list[str], allowed_levels: list[str]) -> JobFacts:
    """Coerce a model reply into JobFacts.

    Deliberately forgiving: a wrong enum value or a salary written as a string
    should degrade that one field, never fail the job.
    """
    family = str(payload.get("family") or "").strip().lower()
    if family not in allowed_families:
        family = "other"

    seniority = str(payload.get("seniority") or "").strip().lower()
    if seniority not in allowed_levels:
        seniority = None

    policy = str(payload.get("remote_policy") or "").strip().lower()
    if policy not in {"remote", "hybrid", "onsite", "unclear"}:
        policy = "unclear"

    currency = payload.get("salary_currency")
    currency = str(currency).strip().upper()[:8] if currency else None

    summary = payload.get("summary")
    summary = str(summary).strip()[:300] if summary else None

    return JobFacts(
        family=family,
        seniority=seniority,
        skills=_clean_list(payload.get("skills")),
        tech_stack=_clean_list(payload.get("tech_stack")),
        years_experience_min=_clean_int(payload.get("years_experience_min")),
        salary_min=_clean_number(payload.get("salary_min")),
        salary_max=_clean_number(payload.get("salary_max")),
        salary_currency=currency,
        remote_policy=policy,
        summary=summary,
    )
