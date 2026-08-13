"""Lever public postings API — no authentication required.

    https://api.lever.co/v0/postings/{board}?mode=json

Board tokens are guesses until proven: an unknown token returns 404 and a valid
but empty board returns []. `jobalert validate-sources` tells the two apart.
"""

from __future__ import annotations

from ..http import get_json
from ..models import NormalisedJob, RawJob
from ..util import parse_dt, strip_html

NAME = "lever"
REQUIRES_BOARD = True
BASE = "https://api.lever.co/v0/postings"


def fetch(board: str) -> list[RawJob]:
    data = get_json(f"{BASE}/{board}", params={"mode": "json"})
    return [
        RawJob(source=NAME, board=board, source_job_id=str(job["id"]), payload=job)
        for job in data
    ]


def normalise(raw: RawJob) -> NormalisedJob | None:
    job = raw.payload
    title = job.get("text")  # Lever calls the job title "text"
    url = job.get("hostedUrl") or job.get("applyUrl")
    if not title or not url:
        return None

    categories = job.get("categories") or {}
    workplace = (job.get("workplaceType") or "").lower()

    description = job.get("descriptionPlain") or strip_html(job.get("description"))

    return NormalisedJob(
        source=NAME,
        board=raw.board,
        source_job_id=raw.source_job_id,
        company=(raw.board or "").title(),
        title=title,
        location=categories.get("location"),
        remote=workplace == "remote",
        url=url,
        description=description,
        posted_at=parse_dt(job.get("createdAt")),  # epoch milliseconds
    )
