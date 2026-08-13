"""Ashby public job board API — no authentication required.

    https://api.ashbyhq.com/posting-api/job-board/{org}
"""

from __future__ import annotations

from ..http import get_json
from ..models import NormalisedJob, RawJob
from ..util import parse_dt, strip_html

NAME = "ashby"
REQUIRES_BOARD = True
BASE = "https://api.ashbyhq.com/posting-api/job-board"


def fetch(board: str) -> list[RawJob]:
    data = get_json(f"{BASE}/{board}")
    return [
        RawJob(source=NAME, board=board, source_job_id=str(job["id"]), payload=job)
        for job in data.get("jobs", [])
        # isListed=false means the posting exists but is not public.
        if job.get("isListed", True)
    ]


def normalise(raw: RawJob) -> NormalisedJob | None:
    job = raw.payload
    title = job.get("title")
    url = job.get("jobUrl") or job.get("applyUrl")
    if not title or not url:
        return None

    # Ashby gives us plain text directly — prefer it over stripping the HTML.
    description = job.get("descriptionPlain") or strip_html(job.get("descriptionHtml"))

    return NormalisedJob(
        source=NAME,
        board=raw.board,
        source_job_id=raw.source_job_id,
        company=(raw.board or "").title(),
        title=title,
        location=job.get("location"),
        remote=bool(job.get("isRemote")),
        url=url,
        description=description,
        posted_at=parse_dt(job.get("publishedAt")),
    )
