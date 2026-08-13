"""Stage 1 — fetch every configured source into the bronze table.

A dead board token must never fail the run. Company lists rot constantly: a
company migrates ATS, renames its board, or goes quiet. Those are expected
conditions, logged and skipped.
"""

from __future__ import annotations

import requests

from .. import db, sources
from ..logging_setup import get_logger
from ..models import RawJob
from ..settings import load_companies

log = get_logger(__name__)


def run() -> dict:
    config = load_companies()
    collected: list[RawJob] = []
    stats = {"boards_ok": 0, "boards_failed": 0, "feeds_ok": 0, "feeds_failed": 0}
    failures: list[str] = []

    # --- per-company boards ------------------------------------------------
    for source_name, module in sources.BOARD_SOURCES.items():
        for board in config.get(source_name, []) or []:
            try:
                jobs = module.fetch(board)
                collected.extend(jobs)
                stats["boards_ok"] += 1
                log.info("%s/%s: %d jobs", source_name, board, len(jobs))
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                stats["boards_failed"] += 1
                failures.append(f"{source_name}/{board} HTTP {status}")
                log.warning("%s/%s: HTTP %s — skipping", source_name, board, status)
            except Exception as exc:  # noqa: BLE001 - one bad board must not stop the run
                stats["boards_failed"] += 1
                failures.append(f"{source_name}/{board} {type(exc).__name__}")
                log.warning("%s/%s: %s — skipping", source_name, board, exc)

    # --- whole-feed sources ------------------------------------------------
    for feed_name, enabled in (config.get("feeds") or {}).items():
        if not enabled:
            continue
        try:
            module = sources.get(feed_name)
            jobs = module.fetch()
            collected.extend(jobs)
            stats["feeds_ok"] += 1
            log.info("%s: %d jobs", feed_name, len(jobs))
        except Exception as exc:  # noqa: BLE001
            stats["feeds_failed"] += 1
            failures.append(f"{feed_name} {type(exc).__name__}")
            log.warning("%s: %s — skipping", feed_name, exc)

    stats["raw_inserted"] = db.insert_raw_jobs(collected)
    stats["failures"] = failures
    log.info(
        "extract complete: %d raw rows, %d boards ok, %d failed",
        stats["raw_inserted"], stats["boards_ok"], stats["boards_failed"],
    )
    return stats
