"""Arbeitnow free job board — no authentication, no board token.

    https://www.arbeitnow.com/api/job-board-api

Paginated; we walk a bounded number of pages so a runaway feed can't stall the
whole extract stage.
"""

from __future__ import annotations

from ..http import get_json
from ..logging_setup import get_logger
from ..models import NormalisedJob, RawJob
from ..util import parse_dt, strip_html

NAME = "arbeitnow"
REQUIRES_BOARD = False
URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 5

log = get_logger(__name__)


def fetch(board: str | None = None) -> list[RawJob]:
    out: list[RawJob] = []
    for page in range(1, MAX_PAGES + 1):
        data = get_json(URL, params={"page": page})
        rows = data.get("data", [])
        if not rows:
            break
        out.extend(
            RawJob(source=NAME, board=None, source_job_id=str(job["slug"]), payload=job)
            for job in rows
        )
    log.info("arbeitnow: %d postings across up to %d pages", len(out), MAX_PAGES)
    return out


def normalise(raw: RawJob) -> NormalisedJob | None:
    job = raw.payload
    title = job.get("title")
    url = job.get("url")
    if not title or not url:
        return None

    return NormalisedJob(
        source=NAME,
        board=None,
        source_job_id=raw.source_job_id,
        company=job.get("company_name") or "Unknown",
        title=title,
        location=job.get("location"),
        remote=bool(job.get("remote")),
        url=url,
        description=strip_html(job.get("description")),
        posted_at=parse_dt(job.get("created_at")),  # epoch seconds
    )
