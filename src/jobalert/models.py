"""Domain objects shared across stages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(text: str | None) -> str:
    """Lowercase and strip everything that isn't a letter or digit.

    Used only for hashing — 'Senior Data Engineer (Remote)' and
    'senior data engineer  remote' must collapse to the same key.
    """
    if not text:
        return ""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def job_hash(company: str, title: str, location: str | None) -> str:
    """Stable identity for a job across boards.

    Deliberately excludes the URL and source: the same role posted to Greenhouse
    and scraped into an aggregator should be one job, not two.
    """
    key = f"{normalise(company)}|{normalise(title)}|{normalise(location)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


@dataclass
class RawJob:
    """One posting exactly as the source returned it."""

    source: str
    board: str | None
    source_job_id: str
    payload: dict[str, Any]


@dataclass
class NormalisedJob:
    """A posting mapped onto our own shape."""

    source: str
    board: str | None
    source_job_id: str
    company: str
    title: str
    location: str | None
    remote: bool | None
    url: str
    description: str | None
    posted_at: datetime | None

    @property
    def hash(self) -> str:
        return job_hash(self.company, self.title, self.location)


@dataclass
class JobFacts:
    """Structure extracted from the description by the LLM."""

    family: str | None = None
    seniority: str | None = None
    skills: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    years_experience_min: int | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    remote_policy: str | None = None
    summary: str | None = None
