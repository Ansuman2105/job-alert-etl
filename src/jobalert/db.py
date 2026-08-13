"""Postgres access layer.

Every write is idempotent. Re-running any stage after a crash must not create
duplicates or skip rows — that property is what makes the pipeline safe to
retry from the Actions tab without thinking about it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from .logging_setup import get_logger
from .models import JobFacts, NormalisedJob, RawJob
from .settings import get_settings

log = get_logger(__name__)
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    conn = psycopg2.connect(get_settings().database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
    log.info("schema ready")


# --------------------------------------------------------------------------
# Bronze
# --------------------------------------------------------------------------

def insert_raw_jobs(raw: list[RawJob]) -> int:
    if not raw:
        return 0
    rows = [(r.source, r.board, r.source_job_id, json.dumps(r.payload)) for r in raw]
    with connect() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO raw_jobs (source, board, source_job_id, payload) VALUES %s",
            rows,
            page_size=500,
        )
    return len(rows)


def fetch_raw_for_transform(lookback_days: int = 3) -> list[RawJob]:
    """Latest payload per job within the lookback window.

    DISTINCT ON collapses repeated daily fetches of the same posting down to the
    most recent copy, so transform is cheap to re-run and always sees current data.
    """
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (source, board, source_job_id)
                   source, board, source_job_id, payload
              FROM raw_jobs
             WHERE fetched_at > now() - make_interval(days => %s)
             ORDER BY source, board, source_job_id, fetched_at DESC
            """,
            (lookback_days,),
        )
        return [
            RawJob(
                source=r["source"],
                board=r["board"],
                source_job_id=r["source_job_id"],
                payload=r["payload"],
            )
            for r in cur.fetchall()
        ]


# --------------------------------------------------------------------------
# Silver
# --------------------------------------------------------------------------

def upsert_jobs(jobs: list[NormalisedJob]) -> tuple[int, int]:
    """Insert new jobs, refresh last_seen on ones we already had.

    Returns (inserted, refreshed).
    """
    if not jobs:
        return (0, 0)

    rows = [
        (
            j.hash, j.source, j.board, j.source_job_id, j.company, j.title,
            j.location, j.remote, j.url, j.description, j.posted_at,
        )
        for j in jobs
    ]

    with connect() as conn, conn.cursor() as cur:
        # fetch=True is required with RETURNING: execute_values sends the rows in
        # pages, and a plain cur.fetchall() afterwards sees only the final page.
        results = psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO jobs (job_hash, source, board, source_job_id, company,
                              title, location, remote, url, description, posted_at)
            VALUES %s
            ON CONFLICT (job_hash) DO UPDATE
               SET last_seen   = now(),
                   -- only fill gaps; never overwrite good data with nulls
                   description = COALESCE(EXCLUDED.description, jobs.description),
                   posted_at   = COALESCE(jobs.posted_at, EXCLUDED.posted_at)
            RETURNING (xmax = 0) AS inserted
            """,
            rows,
            page_size=500,
            fetch=True,
        )

    inserted = sum(1 for (is_new,) in results if is_new)
    return (inserted, len(results) - inserted)


# --------------------------------------------------------------------------
# Enrichment
# --------------------------------------------------------------------------

def fetch_unenriched(limit: int) -> list[dict[str, Any]]:
    """Jobs with no LLM facts yet, newest first."""
    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT j.job_hash, j.company, j.title, j.location, j.description
              FROM jobs j
              LEFT JOIN job_facts f USING (job_hash)
             WHERE f.job_hash IS NULL
             ORDER BY j.first_seen DESC
             LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def save_facts(job_hash: str, facts: JobFacts, model: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_facts (job_hash, family, seniority, skills, tech_stack,
                                   years_experience_min, salary_min, salary_max,
                                   salary_currency, remote_policy, summary, model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_hash) DO UPDATE
               SET family = EXCLUDED.family,
                   seniority = EXCLUDED.seniority,
                   skills = EXCLUDED.skills,
                   tech_stack = EXCLUDED.tech_stack,
                   years_experience_min = EXCLUDED.years_experience_min,
                   salary_min = EXCLUDED.salary_min,
                   salary_max = EXCLUDED.salary_max,
                   salary_currency = EXCLUDED.salary_currency,
                   remote_policy = EXCLUDED.remote_policy,
                   summary = EXCLUDED.summary,
                   model = EXCLUDED.model,
                   enriched_at = now()
            """,
            (
                job_hash, facts.family, facts.seniority, facts.skills, facts.tech_stack,
                facts.years_experience_min, facts.salary_min, facts.salary_max,
                facts.salary_currency, facts.remote_policy, facts.summary, model,
            ),
        )


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------

def fetch_publishable(
    channel: str,
    limit: int,
    max_age_days: int,
    families: list[str] | None = None,
    location_regex: str | None = None,
    location_match: bool = True,
) -> list[dict[str, Any]]:
    """Enriched jobs not yet sent to this channel.

    Ordered oldest-first so a backlog drains in the order jobs appeared rather
    than newest-first, which would leave old jobs permanently stranded.

    `location_regex` routes by location: with location_match=True only matching
    jobs are returned, with False only non-matching ones. Filtering in SQL
    rather than in Python keeps LIMIT meaningful — otherwise a limit of 60 could
    return 60 rows that all belong to the other channel.
    """
    sql = """
        SELECT j.job_hash, j.company, j.title, j.location, j.url, j.remote,
               f.family, f.seniority, f.skills, f.salary_min, f.salary_max,
               f.salary_currency, f.summary
          FROM jobs j
          JOIN job_facts f USING (job_hash)
          LEFT JOIN posted_jobs p
                 ON p.job_hash = j.job_hash AND p.channel = %s
         WHERE p.job_hash IS NULL
           AND j.first_seen > now() - make_interval(days => %s)
    """
    params: list[Any] = [channel, max_age_days]

    if families:
        sql += " AND f.family = ANY(%s)"
        params.append(families)

    if location_regex:
        # COALESCE matters: a NULL location makes the whole predicate NULL,
        # which excludes the row from BOTH channels rather than one.
        operator = "~*" if location_match else "!~*"
        sql += f" AND COALESCE(j.location, '') {operator} %s"
        params.append(location_regex)

    sql += " ORDER BY j.first_seen ASC LIMIT %s"
    params.append(limit)

    with connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def mark_posted(job_hashes: list[str], channel: str, message_id: int | None) -> None:
    """Record delivery. Called only after Telegram returns success."""
    if not job_hashes:
        return
    rows = [(h, channel, message_id) for h in job_hashes]
    with connect() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO posted_jobs (job_hash, channel, message_id) VALUES %s
            ON CONFLICT (job_hash, channel) DO NOTHING
            """,
            rows,
        )


def seed_posted(channel: str) -> int:
    """Mark every known job as already sent, without sending anything.

    Run once, after the first extract, so day one does not fire thousands of
    messages at a brand-new channel. From then on only genuinely new jobs post.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posted_jobs (job_hash, channel, message_id)
            SELECT job_hash, %s, NULL FROM jobs
            ON CONFLICT (job_hash, channel) DO NOTHING
            """,
            (channel,),
        )
        return cur.rowcount


# --------------------------------------------------------------------------
# Observability
# --------------------------------------------------------------------------

def start_run(stage: str) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (stage) VALUES (%s) RETURNING run_id", (stage,)
        )
        return cur.fetchone()[0]


def finish_run(run_id: int, status: str, stats: dict | None = None, error: str | None = None):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
               SET finished_at = now(), status = %s, stats = %s, error = %s
             WHERE run_id = %s
            """,
            (status, json.dumps(stats or {}), error, run_id),
        )


def route_preview(location_regex: str) -> dict[str, int]:
    """How the current `jobs` table splits across routes. Read-only."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE COALESCE(location, '') ~* %s)  AS india,
                   count(*) FILTER (WHERE COALESCE(location, '') !~* %s) AS international
              FROM jobs
            """,
            (location_regex, location_regex),
        )
        india, international = cur.fetchone()
        return {"india": india, "international": international}


def posted_counts() -> dict[str, int]:
    """Rows in posted_jobs per channel — confirms a backfill actually covered
    every channel, which is the easiest thing to get wrong when adding one."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT channel, count(*) FROM posted_jobs GROUP BY channel ORDER BY channel")
        return dict(cur.fetchall())


def counts() -> dict[str, int]:
    """Row counts for the status command."""
    with connect() as conn, conn.cursor() as cur:
        out = {}
        for table in ("raw_jobs", "jobs", "job_facts", "posted_jobs"):
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed literals
            out[table] = cur.fetchone()[0]
        return out
