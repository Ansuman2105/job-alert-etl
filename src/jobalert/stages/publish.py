"""Stage 4 — publish enriched jobs to Telegram.

The ordering here is the important part: mark_posted runs only after Telegram
confirms the message. A crash between send and record would re-post a batch;
a crash before send loses nothing.
"""

from __future__ import annotations

import time

from .. import db, telegram
from ..logging_setup import get_logger
from ..settings import get_settings, load_profile

log = get_logger(__name__)


def run(limit: int | None = None, dry_run: bool = False) -> dict:
    settings = get_settings()
    profile = load_profile()
    publish_cfg = profile.get("publish", {})

    channel = settings.telegram_channel_id
    limit = limit or settings.publish_limit
    batch_size = max(1, settings.publish_batch_size)

    families = None
    if publish_cfg.get("filter_by_family"):
        families = [f.lower() for f in publish_cfg.get("include_families", [])]
        if not families:
            log.warning("filter_by_family is true but include_families is empty — publishing none")
            return {"selected": 0, "sent": 0, "messages": 0}

    jobs = db.fetch_publishable(
        channel=channel,
        limit=limit,
        max_age_days=int(publish_cfg.get("max_age_days", 45)),
        families=families,
    )

    if not jobs:
        log.info("nothing new to publish")
        return {"selected": 0, "sent": 0, "messages": 0}

    log.info("publishing %d jobs in batches of %d", len(jobs), batch_size)

    sent = messages = 0
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start : start + batch_size]
        hashes = [j["job_hash"] for j in batch]

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
            log.error("telegram send failed, batch left unposted: %s", exc)
            break

        db.mark_posted(hashes, channel, message_id)
        sent += len(batch)
        messages += 1

        if start + batch_size < len(jobs):
            time.sleep(telegram.SECONDS_BETWEEN_MESSAGES)

    stats = {"selected": len(jobs), "sent": sent, "messages": messages, "dry_run": dry_run}
    log.info("publish complete: %d jobs in %d messages", sent, messages)
    return stats
