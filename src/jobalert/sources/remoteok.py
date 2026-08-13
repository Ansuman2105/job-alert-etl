"""RemoteOK public feed — no authentication, no board token.

    https://remoteok.com/api

The first element of the response is a legal/attribution notice rather than a
job, so it is dropped. The feed also rejects requests without a User-Agent,
which our shared session already sets.
"""

from __future__ import annotations

from ..http import get_json
from ..models import NormalisedJob, RawJob
from ..util import parse_dt, strip_html

NAME = "remoteok"
REQUIRES_BOARD = False
URL = "https://remoteok.com/api"


def fetch(board: str | None = None) -> list[RawJob]:
    data = get_json(URL)
    return [
        RawJob(source=NAME, board=None, source_job_id=str(job["id"]), payload=job)
        for job in data
        # The notice element has no "id"; real postings always do.
        if isinstance(job, dict) and job.get("id")
    ]


def normalise(raw: RawJob) -> NormalisedJob | None:
    job = raw.payload
    title = job.get("position")
    url = job.get("url") or job.get("apply_url")
    if not title or not url:
        return None

    return NormalisedJob(
        source=NAME,
        board=None,
        source_job_id=raw.source_job_id,
        company=job.get("company") or "Unknown",
        title=title,
        location=job.get("location") or "Remote",
        remote=True,  # the entire board is remote-only
        url=url,
        description=strip_html(job.get("description")),
        posted_at=parse_dt(job.get("date") or job.get("epoch")),
    )
