"""Stage 2 — bronze to silver: normalise, deduplicate, upsert.

Deduplication happens here rather than at publish time so the LLM is never
asked to enrich the same role twice because two boards carry it.
"""

from __future__ import annotations

from .. import db, sources
from ..logging_setup import get_logger
from ..models import NormalisedJob

log = get_logger(__name__)


def run(lookback_days: int = 3) -> dict:
    raw = db.fetch_raw_for_transform(lookback_days)
    log.info("normalising %d raw rows", len(raw))

    normalised: dict[str, NormalisedJob] = {}
    skipped = 0

    for item in raw:
        try:
            module = sources.get(item.source)
        except KeyError:
            skipped += 1
            continue

        try:
            job = module.normalise(item)
        except Exception as exc:  # noqa: BLE001 - a malformed posting is not a run failure
            log.warning("normalise failed for %s/%s: %s", item.source, item.source_job_id, exc)
            skipped += 1
            continue

        if job is None:
            skipped += 1
            continue

        # Collapse duplicates inside this batch too — the same role can appear on
        # a company board and an aggregator in the same run.
        normalised.setdefault(job.hash, job)

    inserted, refreshed = db.upsert_jobs(list(normalised.values()))
    stats = {
        "raw_read": len(raw),
        "unique_jobs": len(normalised),
        "new_jobs": inserted,
        "seen_again": refreshed,
        "skipped": skipped,
    }
    log.info(
        "transform complete: %d unique (%d new, %d already known), %d skipped",
        len(normalised), inserted, refreshed, skipped,
    )
    return stats
