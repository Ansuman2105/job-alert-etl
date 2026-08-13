"""Stage 3 — LLM extraction into job_facts.

Bounded by ENRICH_LIMIT so a large backlog drains over several days rather than
exhausting a free-tier daily quota in one run. Jobs left unenriched are simply
picked up next time.
"""

from __future__ import annotations

from .. import db, llm
from ..llm import LLMError
from ..logging_setup import get_logger
from ..settings import get_settings, load_profile

log = get_logger(__name__)


def run(limit: int | None = None) -> dict:
    settings = get_settings()
    limit = limit or settings.enrich_limit

    pending = db.fetch_unenriched(limit)
    if not pending:
        log.info("nothing to enrich")
        return {"attempted": 0, "enriched": 0, "failed": 0}

    client = llm.get_client()
    profile = load_profile()
    families = [f.lower() for f in profile.get("families", [])]
    levels = [s.lower() for s in profile.get("seniority_levels", [])]
    system_prompt = llm.build_system_prompt()

    log.info("enriching %d jobs via %s/%s", len(pending), client.name, client.model)

    enriched = failed = 0
    consecutive_failures = 0

    for job in pending:
        user_prompt = llm.build_user_prompt(
            job["company"], job["title"], job.get("location"), job.get("description")
        )

        try:
            payload = client.complete_json(system_prompt, user_prompt)
            facts = llm.parse_facts(payload, families, levels)
            db.save_facts(job["job_hash"], facts, client.model)
            enriched += 1
            consecutive_failures = 0
        except LLMError as exc:
            failed += 1
            consecutive_failures += 1
            log.warning("enrich failed for %s: %s", job["title"][:60], exc)

            # A rate limit or an expired key fails every call. Stop early rather
            # than burning the rest of the batch against the same wall.
            if consecutive_failures >= 5:
                log.error("5 consecutive LLM failures — stopping this run early")
                break
        except Exception as exc:  # noqa: BLE001
            failed += 1
            consecutive_failures += 1
            log.warning("unexpected error enriching %s: %s", job["title"][:60], exc)

    stats = {"attempted": len(pending), "enriched": enriched, "failed": failed}
    log.info("enrich complete: %d ok, %d failed", enriched, failed)
    return stats
