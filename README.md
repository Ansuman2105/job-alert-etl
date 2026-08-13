# job-alert-etl

Pulls job postings from public ATS boards, enriches them with an LLM, and posts
them to a Telegram channel. Runs entirely on free infrastructure — GitHub
Actions for scheduling, Neon for Postgres, Groq or Gemini for the LLM. No
server, no local machine, no cost.

```
ATS boards ──► raw_jobs ──► jobs ──► job_facts ──► Telegram
(Greenhouse   (bronze:     (silver:  (gold:        (posted_jobs
 Ashby        immutable    deduped   LLM-extracted  = dedup ledger)
 Lever        JSON)        on hash)  structure)
 Arbeitnow
 RemoteOK)
```

---

## Where your credentials go

**Never in a file, never in the code, never pasted into a chat.**
They live in two places only:

### Production — GitHub

Repo → **Settings** → **Secrets and variables** → **Actions**

On the **Secrets** tab, click *New repository secret* for each:

| Secret name | Where to get it |
|---|---|
| `DATABASE_URL` | neon.tech → your project → **Connection string** → psycopg2 (keep `?sslmode=require`) |
| `GROQ_API_KEY` | console.groq.com → **API Keys** → Create |
| `TELEGRAM_BOT_TOKEN` | Telegram → message **@BotFather** → `/newbot` |
| `TELEGRAM_CHANNEL_INDIA` | `@your_india_channel` — jobs located in India |
| `TELEGRAM_CHANNEL_INTERNATIONAL` | `@your_intl_channel` — everything else |
| `TELEGRAM_CHANNEL_ID` | fallback for any route above that is unset; also the default alert target |
| `GEMINI_API_KEY` | optional — aistudio.google.com, only if you switch providers |
| `TELEGRAM_ALERT_CHANNEL_ID` | optional — a private channel for failure alerts |

The same bot serves every channel — one token, and it must be an admin of each.

On the **Variables** tab (these are *not* secret, and are visible in logs):

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq` or `gemini` |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | update if the model is retired |
| `ENRICH_LIMIT` | `250` | jobs sent to the LLM per run |
| `PUBLISH_LIMIT` | `60` | jobs published per run |
| `PUBLISH_BATCH_SIZE` | `5` | jobs bundled into one Telegram message |

Secrets are write-only once saved — GitHub will never show them again, and they
are masked in workflow logs. Rotating one means pasting a new value over the old.

### Local development — `.env`

```bash
cp .env.example .env      # then fill it in
```

`.env` is in `.gitignore` and must stay there. It is a convenience for running
stages on your laptop; production never reads it.

> **The bot must be an admin of the channel.** Create the channel, open its
> settings, Administrators → Add Admin → your bot. Without this, every send
> fails with `chat not found` even though the token is correct.

---

## First run

Order matters here — the backfill step is what stops your brand-new channel
receiving ~6,000 messages on day one.

```bash
python -m jobalert init-db           # create tables
python -m jobalert validate-sources  # confirm your board tokens are alive
python -m jobalert extract           # ~6,000 postings into bronze
python -m jobalert transform         # normalise + dedupe into silver
python -m jobalert seed-posted --yes # mark all of it as "already sent"
```

From that point on, only genuinely new postings are published. Then:

```bash
python -m jobalert enrich            # LLM extraction, bounded by ENRICH_LIMIT
python -m jobalert publish --dry-run # print the messages, send nothing
python -m jobalert publish           # actually send
```

Skip `seed-posted` only if you want the entire back catalogue posted.

---

## Commands

| Command | What it does |
|---|---|
| `init-db` | Create tables. Idempotent — safe on every run. |
| `validate-sources` | Test every token in `companies.yaml`, report DEAD ones. |
| `extract` | Fetch all sources into `raw_jobs`. |
| `transform` | Normalise and dedupe into `jobs`. |
| `enrich` | LLM extraction into `job_facts`. |
| `publish` | Send new jobs to Telegram. `--dry-run` prints instead. |
| `run` | All four stages in order. |
| `seed-posted --yes` | Suppress the first-run flood. |
| `status` | Row counts per table. |

Add `--no-alert` to any stage to suppress the Telegram failure message.

---

## Running it from your phone

- **Trigger a run:** GitHub mobile app → **Actions** → *pipeline* → **Run workflow**.
  Pick a single stage from the dropdown, or `run` for everything.
- **Change what's tracked:** edit `config/companies.yaml` on github.com. The
  commit alone is enough; the next scheduled run picks it up.
- **Inspect the data:** Neon's web SQL editor works on mobile.
- **See failures:** they arrive in your Telegram alert channel, and the Actions
  tab shows the full log.

The schedule is `30 5 * * *` UTC = **11:00 IST**. GitHub cron is UTC-only and
scheduled runs are queued rather than guaranteed — expect up to ~20 minutes of
drift, and occasional skips under heavy load. Use *Run workflow* when you need
it now.

---

## Configuration

**`config/companies.yaml`** — ATS board tokens, one list per provider, plus
toggles for the whole-feed sources. Every token was verified live; re-run
`validate-sources` after editing.

**`config/profile.yaml`** — publishing policy. Currently publishes *everything*.
The LLM still tags each job with a `family` and `seniority`, so when you split
into per-topic channels later, that is a routing change against data you already
have — not a re-enrichment of your history.

To start filtering, set `filter_by_family: true` and list the families you want.

### Channel routing

Every job goes to exactly one channel, decided by its **location string** —
a rule, not an LLM call. It costs nothing, is identical for the same input every
time, and applies retroactively to jobs enriched before routing existed.

```yaml
routing:
  channels:
    india: TELEGRAM_CHANNEL_INDIA          # the env var NAME, not the value
    international: TELEGRAM_CHANNEL_INTERNATIONAL
  india_location_patterns: [india, bengaluru, pune, ...]
```

Matching is on **whole words**. That detail is load-bearing: a plain substring
match on `india` also catches `Indianapolis, IN` and `Indiana`, quietly routing
US jobs to the India channel. Postgres spells the word boundary `\y` (not `\b`,
which means backspace there and silently matches nothing) — `routing.py`
generates both dialects from the one pattern list.

A job with no location routes to `international` rather than disappearing from
both channels.

**Adding a channel later:** add the route to `routing.channels`, add its secret,
then run `seed-posted` — a new channel's `posted_jobs` is empty, so without the
backfill its first publish treats your entire back catalogue as new. Run
`status` to see the routing split and the per-channel posted counts.

---

## Design notes

**Why bronze/silver/gold.** `raw_jobs` is never edited. When the parsing logic
turns out to be wrong — and it will, these feeds are inconsistent — you reparse
from bronze instead of re-fetching thousands of postings.

**Why `job_hash` excludes the URL.** The same role appears on a company board
*and* an aggregator. Hashing company + title + location collapses them into one
job, so the LLM never pays to enrich a duplicate.

**Why `posted_jobs` is written after Telegram confirms.** A crash between
sending and recording would repost a batch. This ordering means a crash costs
you a retry, never a duplicate.

**Why the limits exist.** `ENRICH_LIMIT` keeps a backlog from exhausting a
free-tier daily quota in one run; `PUBLISH_LIMIT` and the 3.5s pause keep us
under Telegram's ~20 messages/minute ceiling. A backlog drains over several
days rather than failing loudly.

**Why a dead board token is a warning, not an error.** Company lists rot
constantly — 7 of the 30 seed tokens were already dead when this was built.
One 404 must not fail the run.

---

## Cost

Zero, at this scale:

| | Free allowance | This project uses |
|---|---|---|
| GitHub Actions | unlimited (public repo) | ~10 min/day |
| Neon Postgres | ~0.5 GB | well under |
| Groq | ~30 req/min | 250 calls/day, throttled to fit |
| Telegram | unlimited | ~12 messages/day |

---

## Development

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

Tests need neither network nor a database — source normalisation is tested
against payload shapes captured from the live APIs, so a provider renaming a
field breaks a test rather than silently producing rows full of nulls.
