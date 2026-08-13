"""Greenhouse public job board API — no authentication required.

    https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
"""

from __future__ import annotations

import html

from ..http import get_json
from ..models import NormalisedJob, RawJob
from ..util import parse_dt, strip_html

NAME = "greenhouse"
REQUIRES_BOARD = True
BASE = "https://boards-api.greenhouse.io/v1/boards"


def fetch(board: str) -> list[RawJob]:
    data = get_json(f"{BASE}/{board}/jobs", params={"content": "true"})
    return [
        RawJob(source=NAME, board=board, source_job_id=str(job["id"]), payload=job)
        for job in data.get("jobs", [])
    ]


def normalise(raw: RawJob) -> NormalisedJob | None:
    job = raw.payload
    title = job.get("title")
    url = job.get("absolute_url")
    if not title or not url:
        return None

    location = (job.get("location") or {}).get("name")

    # Greenhouse returns the description as HTML-entity-encoded HTML, so it must
    # be unescaped *before* tags are stripped — otherwise the tags survive as
    # literal text in the output.
    content = job.get("content")
    description = strip_html(html.unescape(content)) if content else None

    return NormalisedJob(
        source=NAME,
        board=raw.board,
        source_job_id=raw.source_job_id,
        company=job.get("company_name") or (raw.board or "").title(),
        title=title,
        location=location,
        remote=bool(location and "remote" in location.lower()),
        url=url,
        description=description,
        posted_at=parse_dt(job.get("first_published") or job.get("updated_at")),
    )
