-- Applied on every run. Every statement is idempotent, so this doubles as the
-- migration mechanism for a project this size.

-- Bronze: exactly what the API returned, never edited. Reparse from here when
-- the transform logic turns out to be wrong.
-- Only rows whose payload_hash differs from the last stored copy are inserted,
-- and anything past the retention window is pruned. Without both, six runs a
-- day x ~6,400 postings x a full job description fills a 512 MB database in
-- about four days.
CREATE TABLE IF NOT EXISTS raw_jobs (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,
    board         TEXT,
    source_job_id TEXT        NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload       JSONB       NOT NULL,
    payload_hash  TEXT
);
CREATE INDEX IF NOT EXISTS raw_jobs_fetched_idx ON raw_jobs (fetched_at DESC);
CREATE INDEX IF NOT EXISTS raw_jobs_source_idx  ON raw_jobs (source, board);
CREATE INDEX IF NOT EXISTS raw_jobs_identity_idx
    ON raw_jobs (source, board, source_job_id, fetched_at DESC);

-- Silver: one row per unique job. job_hash is company+title+location normalised,
-- so the same role listed on three boards collapses to one row.
CREATE TABLE IF NOT EXISTS jobs (
    job_hash      TEXT PRIMARY KEY,
    source        TEXT        NOT NULL,
    board         TEXT,
    source_job_id TEXT        NOT NULL,
    company       TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    location      TEXT,
    remote        BOOLEAN,
    url           TEXT        NOT NULL,
    description   TEXT,
    posted_at     TIMESTAMPTZ,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_first_seen_idx ON jobs (first_seen DESC);
CREATE INDEX IF NOT EXISTS jobs_company_idx    ON jobs (company);

-- Gold: LLM-extracted structure. Separate table so re-enriching never risks
-- the source-of-truth job row.
CREATE TABLE IF NOT EXISTS job_facts (
    job_hash             TEXT PRIMARY KEY REFERENCES jobs (job_hash) ON DELETE CASCADE,
    family               TEXT,
    seniority            TEXT,
    skills               TEXT[],
    tech_stack           TEXT[],
    years_experience_min INTEGER,
    salary_min           NUMERIC,
    salary_max           NUMERIC,
    salary_currency      TEXT,
    remote_policy        TEXT,
    summary              TEXT,
    model                TEXT,
    enriched_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_facts_family_idx ON job_facts (family);

-- The dedup ledger. Written only after Telegram confirms delivery, so a crashed
-- run re-posts nothing and drops nothing.
CREATE TABLE IF NOT EXISTS posted_jobs (
    job_hash   TEXT        NOT NULL REFERENCES jobs (job_hash) ON DELETE CASCADE,
    channel    TEXT        NOT NULL,
    message_id BIGINT,
    posted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_hash, channel)
);

-- Observability: one row per stage execution.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      BIGSERIAL PRIMARY KEY,
    stage       TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT        NOT NULL DEFAULT 'running',
    stats       JSONB,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS pipeline_runs_started_idx ON pipeline_runs (started_at DESC);
