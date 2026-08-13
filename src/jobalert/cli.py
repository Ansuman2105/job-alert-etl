"""Command line entry point.

    python -m jobalert <command>

Every stage is separately invokable so a failure is retried in isolation rather
than by re-running the whole pipeline.
"""

from __future__ import annotations

import argparse
import sys
import traceback

import requests

from . import db, sources, telegram
from .logging_setup import configure, get_logger
from .stages import enrich, extract, publish, transform

log = get_logger("jobalert.cli")


def _tracked(stage_name: str, func, *args, alert: bool = True, **kwargs) -> dict:
    """Run a stage, recording start/finish in pipeline_runs."""
    run_id = db.start_run(stage_name)
    try:
        stats = func(*args, **kwargs)
        db.finish_run(run_id, "success", stats)
        return stats
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        db.finish_run(run_id, "failed", None, error)
        log.error("stage %s failed: %s", stage_name, error)
        log.debug(traceback.format_exc())
        if alert:
            telegram.notify_failure(stage_name, error)
        raise


def cmd_init_db(_: argparse.Namespace) -> int:
    db.init_schema()
    print("Schema created. Tables:", ", ".join(db.counts()))
    return 0


def cmd_validate_sources(_: argparse.Namespace) -> int:
    """Test every board token in companies.yaml and report what actually works."""
    from .settings import load_companies

    config = load_companies()
    dead: list[str] = []

    for source_name, module in sources.BOARD_SOURCES.items():
        boards = config.get(source_name, []) or []
        if boards:
            print(f"\n{source_name}:")
        for board in boards:
            try:
                jobs = module.fetch(board)
                if jobs:
                    print(f"  OK    {board:<20} {len(jobs)} jobs")
                else:
                    print(f"  EMPTY {board:<20} valid token, zero postings")
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                print(f"  DEAD  {board:<20} HTTP {status}")
                dead.append(f"{source_name}/{board}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ERROR {board:<20} {type(exc).__name__}: {exc}")
                dead.append(f"{source_name}/{board}")

    if dead:
        print(f"\n{len(dead)} dead token(s) — remove from config/companies.yaml:")
        for entry in dead:
            print(f"  - {entry}")
    else:
        print("\nAll tokens valid.")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    print(_tracked("extract", extract.run, alert=not args.no_alert))
    return 0


def cmd_transform(args: argparse.Namespace) -> int:
    print(_tracked("transform", transform.run, args.lookback_days, alert=not args.no_alert))
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    print(_tracked("enrich", enrich.run, args.limit, alert=not args.no_alert))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    print(
        _tracked(
            "publish", publish.run, args.limit, args.dry_run, alert=not args.no_alert
        )
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Full pipeline. A failed stage aborts the rest — later stages depend on earlier ones."""
    _tracked("extract", extract.run, alert=not args.no_alert)
    _tracked("transform", transform.run, 3, alert=not args.no_alert)
    _tracked("enrich", enrich.run, None, alert=not args.no_alert)
    _tracked("publish", publish.run, None, False, alert=not args.no_alert)
    print(db.counts())
    return 0


def cmd_seed_posted(args: argparse.Namespace) -> int:
    """Mark everything currently known as already published, without sending.

    Seeds every configured channel by default. Adding a new channel means its
    posted_jobs is empty, so without this the next publish treats the entire
    back catalogue as new for that channel.
    """
    from .settings import resolve_channels

    channels = {"manual": args.channel} if args.channel else resolve_channels()

    if not args.yes:
        print("This marks every job currently in the database as already posted to:")
        for route, channel in channels.items():
            print(f"  {route:<15} {channel}")
        print("\nThey will never be published. Intended for first-run backfill.")
        print("Re-run with --yes to proceed.")
        return 1

    for route, channel in channels.items():
        count = db.seed_posted(channel)
        print(f"[{route}] marked {count} existing jobs as already posted.")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    from . import routing

    for table, count in db.counts().items():
        print(f"{table:<14} {count:>8}")

    print("\nRouting split (all jobs):")
    for route, count in db.route_preview(routing.postgres_regex()).items():
        print(f"  {route:<15} {count:>8}")

    posted = db.posted_counts()
    if posted:
        print("\nAlready posted, per channel:")
        for channel, count in posted.items():
            print(f"  {channel:<15} {count:>8}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobalert", description=__doc__)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="do not send a Telegram message when a stage fails",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create tables (idempotent)").set_defaults(func=cmd_init_db)
    sub.add_parser("validate-sources", help="test every board token").set_defaults(
        func=cmd_validate_sources
    )
    sub.add_parser("status", help="row counts").set_defaults(func=cmd_status)
    sub.add_parser("extract", help="fetch sources into raw_jobs").set_defaults(func=cmd_extract)

    p_transform = sub.add_parser("transform", help="normalise raw_jobs into jobs")
    p_transform.add_argument("--lookback-days", type=int, default=3)
    p_transform.set_defaults(func=cmd_transform)

    p_enrich = sub.add_parser("enrich", help="LLM extraction into job_facts")
    p_enrich.add_argument("--limit", type=int, default=None)
    p_enrich.set_defaults(func=cmd_enrich)

    p_publish = sub.add_parser("publish", help="send new jobs to Telegram")
    p_publish.add_argument("--limit", type=int, default=None)
    p_publish.add_argument("--dry-run", action="store_true", help="print instead of sending")
    p_publish.set_defaults(func=cmd_publish)

    sub.add_parser("run", help="extract -> transform -> enrich -> publish").set_defaults(
        func=cmd_run
    )

    p_seed = sub.add_parser("seed-posted", help="backfill: suppress the first-run flood")
    p_seed.add_argument("--channel", default=None)
    p_seed.add_argument("--yes", action="store_true")
    p_seed.set_defaults(func=cmd_seed_posted)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure(args.log_level)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - top level: log and exit non-zero
        log.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
