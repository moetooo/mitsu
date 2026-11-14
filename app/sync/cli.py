from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ..core.schema import seed_external_ids, verify_schema
from .service import run_backfill, run_sync, sync_status
from ..config import settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.sync.cli", description="Mitsu catalog sync")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run one idempotent refresh")
    run.add_argument("--mode", choices=("manual", "auto"), default="manual")
    run.add_argument("--dry-run", action="store_true", help="Fetch and report, but roll back catalog writes")
    run.add_argument("--max-pages", type=int, default=None, help="AniList pages for this run (1-30)")
    run.add_argument("--since", default=None, help="Override AniList checkpoint (ISO timestamp)")
    run.add_argument("--skip-anilist", action="store_true")
    run.add_argument("--skip-mangadex", action="store_true")
    run.add_argument("--no-embeddings", action="store_true")

    backfill = sub.add_parser("backfill", help="Refresh every title updated after a cutoff")
    backfill.add_argument("--until", default=settings.SYNC_BACKFILL_CUTOFF)
    backfill.add_argument("--max-pages", type=int, default=None, help="AniList pages for this run (1-30)")
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument("--no-embeddings", action="store_true")
    backfill.add_argument("--budget", type=int, default=None, help="One-off AniList request limit; default is the daily cap")

    sub.add_parser("status", help="Print sync state and recent runs")

    sub.add_parser("migrate", help="Create sync tables/columns and backfill the ID map")
    return parser


async def _run(args: argparse.Namespace) -> int:
    summary = await run_sync(
        mode=args.mode,
        dry_run=args.dry_run,
        max_pages=args.max_pages,
        since=args.since,
        include_anilist=not args.skip_anilist,
        include_mangadex=not args.skip_mangadex,
        generate_embeddings=not args.no_embeddings,
    )
    print(json.dumps(summary, indent=2, default=str))
    return {
        "success": 0,
        "partial": 3,
        "failed": 1,
        "skipped": 2,
        "rejected": 2,
    }.get(summary.get("status"), 1)


async def _backfill(args: argparse.Namespace) -> int:
    summary = await run_backfill(
        until=args.until,
        max_pages=args.max_pages,
        dry_run=args.dry_run,
        generate_embeddings=not args.no_embeddings,
        budget_limit=args.budget,
    )
    print(json.dumps(summary, indent=2, default=str))
    return {
        "success": 0,
        "partial": 3,
        "failed": 1,
        "skipped": 2,
        "rejected": 2,
    }.get(summary.get("status"), 1)


async def _status() -> int:
    print(json.dumps(await sync_status(limit=10), indent=2, default=str))
    return 0


async def _migrate() -> int:
    await verify_schema()
    inserted = await seed_external_ids()
    print(json.dumps({"status": "ok", "seed_inserted": inserted}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.command == "run":
        return asyncio.run(_run(args))
    if args.command == "backfill":
        return asyncio.run(_backfill(args))
    if args.command == "status":
        return asyncio.run(_status())
    if args.command == "migrate":
        return asyncio.run(_migrate())
    return 1


if __name__ == "__main__":
    sys.exit(main())
