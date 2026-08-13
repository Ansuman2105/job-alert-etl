"""Stage 4 — publish enriched jobs to Telegram, routed per channel.

The ordering here is the important part: mark_posted runs only after Telegram
confirms the message. A crash between sending and recording would re-post a
batch; a crash before sending loses nothing.
"""

from __future__ import annotations

import time

from .. import db, routing, telegram
from ..logging_setup import get_logger
from ..settings import get_settings, load_profile, resolve_channels

log = get_logger(__name__)


def _families_filter() -> list[str] | None:
    publish_cfg = load_profile().get("publish", {})
    if not publish_cfg.get("filter_by_family"):
        return None
    families = [f.lower() for f in publish_cfg.get("include_families", [])]
    if not families:
        log.warning("filter_by_family is true but include_families is empty")
    return families


def _publish_one(route: str, channel: str, limit: int, dry_run: bool) -> dict:
    publish_cfg = load_profile().get("publish", {})
    settings = get_settings()
    batch_size = max(1, settings.publish_batch_size)

    jobs = db.fetch_publishable(
        channel=channel,
        limit=limit,
        max_age_days=int(publish_cfg.get("max_age_days", 45)),
        families=_families_filter(),
        location_regex=routing.postgres_regex(),
        location_match=(route == routing.INDIA),
    )

    if not jobs:
        log.info("[%s] nothing new to publish", route)
        return {"selected": 0, "sent": 0, "messages": 0}

    log.info("[%s] publishing %d jobs in batches of %d", route, len(jobs), batch_size)

    sent = messages = 0
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start : start + batch_size]

        if dry_run:
            for job in batch:
                print(telegram.format_job(job))
                print("-" * 60)
            sent += len(batch)
            messages += 1
            continue

        try:
            message_id = telegram.send_digest(channel, batch)
        except telegram.TelegramError as exc:
            # Do not mark as posted — the next run retries this batch.
            log.error("[%s] send failed, batch left unposted: %s", route, exc)
            break

        db.mark_posted([j["job_hash"] for j in batch], channel, message_id)
        sent += len(batch)
        messages += 1

        if start + batch_size < len(jobs):
            time.sleep(telegram.SECONDS_BETWEEN_MESSAGES)

    log.info("[%s] published %d jobs in %d messages", route, sent, messages)
    return {"selected": len(jobs), "sent": sent, "messages": messages}


def run(limit: int | None = None, dry_run: bool = False) -> dict:
    settings = get_settings()
    limit = limit or settings.publish_limit
    channels = resolve_channels()

    totals = {"selected": 0, "sent": 0, "messages": 0, "dry_run": dry_run, "routes": {}}

    for route, channel in channels.items():
        stats = _publish_one(route, channel, limit, dry_run)
        totals["routes"][route] = stats
        for key in ("selected", "sent", "messages"):
            totals[key] += stats[key]

    log.info(
        "publish complete: %d jobs in %d messages across %d channel(s)",
        totals["sent"], totals["messages"], len(channels),
    )
    return totals
