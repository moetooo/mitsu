"""
COVER REPAIR: re-source the covers the catalogue could not load.

`uploads.mangadex.org` began answering 200 with an HTML challenge page, so every
title ingested from MangaDex rendered a broken card. Ingestion no longer mints
those URLs (`app/ingestion/normalize.py`), but the rows already in the database
kept them. This script is the one-off pass that replaces them, and stays useful
afterwards for any title whose cover dies later.

Two sources, chosen by what each row already knows:

  tenrai   - rows with a `mal_id`. 50 ids per request, no daily cap.
  anilist  - rows with only an `anilist_id`. 50 ids per request, charged against
             `ANILIST_DAILY_REQUEST_BUDGET`, so it stops cleanly when spent.

Safety:

  1. Nothing is written without `--apply`; the default is a rehearsal that still
     queries the providers, so the numbers you see are the numbers a real run
     would produce. In rehearsal the AniList budget is checked but not spent.
  2. Only `cover_image_url`, `cover_candidates`, `cover_status`, `cover_source`
     and `cover_checked_at` are touched. No title, id or tag is modified.
  3. Every change is written to `cover_repair_log` with the URL it replaced, in
     the same transaction as the row update.
  4. Idempotent: repaired rows leave the `cover_status = 'dead'` working set, so
     re-running fixes what is left and logs `0 resolved`.
  5. Committed in batches: a crash costs at most one batch, not the whole run.

Modes:

  repair            (default) fix rows whose cover is known dead.
  verify            spot-check covers per host, and mark a row dead only after it
                    has failed on two separate runs.
  second-candidate  give healthy rows a fallback they do not have yet. 52,426
                    titles carry a single AniList URL, so one provider outage
                    leaves them with nothing; a second candidate turns that into
                    a fallback instead of an outage. Tenrai only - AniList is
                    already the primary and its budget is needed for repairs.

Usage:
  python scripts/resolve_covers.py                      # rehearsal, both sources
  python scripts/resolve_covers.py --source tenrai --apply
  python scripts/resolve_covers.py --limit 200 --apply   # smoke run
  python scripts/resolve_covers.py --min-popularity 1000 # popular titles first
  python scripts/resolve_covers.py --mode second-candidate --apply
  python scripts/resolve_covers.py --mode verify --apply         # spot-check
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from sqlalchemy import text, update

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.core.budget import BudgetExceeded, consume, remaining
from app.db import AsyncSessionLocal
from app.db_models import CoverRepairLog, Manga
from app.ingestion.anilist_client import fetch_covers_by_ids
from app.ingestion.tenrai_client import TENRAI_BATCH_SIZE, fetch_covers
from app.services.cache import invalidate_catalog_caches, redis_client
from app.services.covers import (
    cover_fields,
    MAX_CANDIDATES,
    classify_cover,
    host_of,
    make_candidate,
    merge_candidates,
    normalise_candidates,
    primary_url,
)

logger = logging.getLogger("mitsu.covers.repair")
#: Verification is its own area (host sampling, verdicts) with its own logger name,
#: so it can be tuned separately and a log reader can tell the two apart without
#: parsing a `[verify]` prefix out of the message.
verify_logger = logging.getLogger("mitsu.covers.verify")

# --- verification (mode: verify) -------------------------------------------
# A host-level block (MangaDex) and a single rotted URL are different failures and
# need different evidence: the block shows up as every sample failing, rot shows up
# as one sample failing while its neighbours pass. So the run samples a few dozen
# per host, decides the host first, and only then judges individual rows.
VERIFY_SAMPLE_PER_HOST = 30
VERIFY_CONCURRENCY = 8
VERIFY_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=5.0, pool=8.0)

# A host that just failed is not probed again for a while: 30 samples against a
# dead host is waste, and a run in cooldown must not mark rows dead either.
VERIFY_BREAKER_TTL_SECONDS = 6 * 3600
VERIFY_LAST_RUN_KEY = "cover:verify:last_run"
VERIFY_BREAKER_KEY = "cover:verify:hostdown:{host}"

# Two failures on two separate runs before a row is called dead. One timeout is
# noise - 3 AniList fetches timed out at 20 s while the host was perfectly healthy.
VERIFY_FAILURE_WINDOW_DAYS = 14
VERIFY_STRIKES = 2

VERIFY_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# Only hosts the app already believes are renderable. A blocked host is the
# canary's business; probing it here would just mark its rows dead again.
VERIFY_HOSTS = ("s4.anilist.co", "cdn.myanimelist.net", "media.kitsu.app")

VERIFY_SAMPLE_SQL = """
SELECT m.id, m.cover_image_url
FROM manga m
WHERE m.cover_status = 'ok'
  AND m.cover_image_url LIKE :prefix
ORDER BY (
    EXISTS (
        SELECT 1 FROM cover_repair_log l
        WHERE l.manga_id = m.id
          AND l.result = 'reported'
          AND l.created_at > now() - interval '30 days'
    )
) DESC, random()
LIMIT :sample
"""

VERIFY_STRIKES_SQL = """
SELECT manga_id, count(*) AS failures
FROM cover_repair_log
WHERE result = 'failed'
  AND created_at > now() - make_interval(days => :days)
  AND manga_id = ANY(:ids)
GROUP BY manga_id
"""

REPORT_DIR = os.path.join("scratch", "cover_repair")
LAST_RUN_FILE = os.path.join(REPORT_DIR, "last_run.json")
RUNS_FILE = os.path.join(REPORT_DIR, "runs.jsonl")

# Ordered by popularity so a `--limit` smoke run fixes the titles people actually
# see first. `id` breaks ties so paging is stable across runs.
TENRAI_SQL = """
SELECT id, mal_id, cover_image_url, cover_candidates
FROM manga
WHERE cover_status = 'dead'
  AND mal_id IS NOT NULL
  AND (CAST(:min_popularity AS INTEGER) IS NULL OR popularity >= :min_popularity)
ORDER BY popularity DESC NULLS LAST, id
LIMIT CAST(:row_limit AS INTEGER)
"""

# Healthy rows that carry a single candidate. Popularity order again: if the run
# is interrupted, the titles people actually browse already have their fallback.
SECOND_CANDIDATE_SQL = """
SELECT id, mal_id, cover_image_url, cover_candidates
FROM manga
WHERE cover_status = 'ok'
  AND mal_id IS NOT NULL
  AND jsonb_array_length(cover_candidates) < 2
  AND (CAST(:min_popularity AS INTEGER) IS NULL OR popularity >= :min_popularity)
ORDER BY popularity DESC NULLS LAST, id
LIMIT CAST(:row_limit AS INTEGER)
"""

ANILIST_SQL = """
SELECT id, anilist_id, cover_image_url, cover_candidates
FROM manga
WHERE cover_status = 'dead'
  AND mal_id IS NULL
  AND anilist_id IS NOT NULL
  AND (CAST(:min_popularity AS INTEGER) IS NULL OR popularity >= :min_popularity)
ORDER BY popularity DESC NULLS LAST, id
LIMIT CAST(:row_limit AS INTEGER)
"""


def batched(items: Sequence[Any], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def plan_row(row, urls: Sequence[str], phase: str) -> Optional[Dict[str, Any]]:
    """What this row should become, or None when the provider had nothing.

    The new URL is merged into the existing candidate list rather than replacing
    it: a title with a working AniList cover that lost a second provider keeps its
    first choice and only gains a fallback.
    """
    # `source` is derived per URL from its host (mal / anilist / kitsu), not from
    # the phase that fetched it, because that is what `cover_source` records.
    incoming = [c for c in (make_candidate(url) for url in urls if url) if c]
    if not incoming:
        return None

    merged = merge_candidates(row.cover_candidates, incoming)[:MAX_CANDIDATES]
    # Everything that is written comes from the seam, so the repair run cannot
    # disagree with ingestion about what a valid cover is.
    fields = cover_fields(row.cover_image_url, merged)
    new_url = fields["cover_image_url"]
    candidates = fields["cover_candidates"]
    status, provider = fields["cover_status"], fields["cover_source"]
    if not new_url:
        return None

    url_changed = new_url != row.cover_image_url
    list_changed = candidates != normalise_candidates(row.cover_candidates)

    # A healthy row can still need a write: the URL is fine but it just gained a
    # fallback, and skipping that would silently throw the second provider away.
    if not url_changed and not list_changed:
        return None
    if not url_changed and status == "ok" and len(candidates) == 1:
        return None

    return {
        "id": row.id,
        "from_url": row.cover_image_url,
        "to_url": new_url,
        "candidates": candidates,
        "status": status,
        "source": provider,
        "fields": fields,
        "result": "resolved" if url_changed else "fallback",
        "detail": f"{phase} -> {host_of(new_url)}",
    }


async def apply_plans(session, plans: Sequence[Dict[str, Any]], *, apply: bool) -> int:
    """Write the planned rows and their log entries for one batch."""
    if not plans:
        return 0
    if not apply:
        return len(plans)

    now = datetime.now(timezone.utc)
    await session.execute(
        update(Manga),
        [
            {
                "id": plan["id"],
                # The seam's four columns verbatim: one writer, one definition.
                **plan["fields"],
                "cover_checked_at": now,
            }
            for plan in plans
        ],
    )
    session.add_all(
        [
            CoverRepairLog(
                manga_id=plan["id"],
                from_url=plan["from_url"],
                to_url=plan["to_url"],
                source=plan["source"],
                result=plan["result"],
                detail=plan["detail"],
            )
            for plan in plans
        ]
    )
    await session.flush()
    return len(plans)


async def resolve_tenrai(rows, args) -> Dict[int, List[str]]:
    """`{manga_id: [cover_url, ...]}` from Tenrai, keyed by the row not the mal_id."""
    if not rows:
        return {}

    mal_to_rows: Dict[int, List[Any]] = {}
    for row in rows:
        mal_to_rows.setdefault(int(row.mal_id), []).append(row)

    started = time.monotonic()
    covers = await fetch_covers(list(mal_to_rows))
    logger.info(
        "Tenrai: %d mal_id(s) -> %d with a cover (%.1fs, ~%d request(s))",
        len(mal_to_rows), len(covers), time.monotonic() - started,
        max(1, (len(mal_to_rows) + TENRAI_BATCH_SIZE - 1) // TENRAI_BATCH_SIZE),
    )

    # In second-candidate mode one URL per provider is what is wanted: extra
    # variants of the same host add bytes without adding resilience, and they would
    # push the AniList primary out of a capped candidate list.
    keep = 1 if args.mode == "second-candidate" else None

    resolved: Dict[int, List[str]] = {}
    for mal_id, urls in covers.items():
        for row in mal_to_rows.get(mal_id, ()):
            resolved[row.id] = urls[:keep] if keep else urls
    return resolved


async def run_phase(session, sql: str, args, resolve, source: str) -> Dict[str, Any]:
    """Select the working set, resolve it, and write it in batches."""
    rows = (
        await session.execute(
            text(sql), {"row_limit": args.limit, "min_popularity": args.min_popularity}
        )
    ).all()

    summary = {
        "source": source,
        "selected": len(rows),
        "resolved": 0,
        "missed": 0,
        "missing_from_provider": 0,
        "written": 0,
        "urls": {},
    }
    if not rows:
        logger.info("%s: nothing to repair", source.capitalize())
        return summary

    resolved = await resolve(rows, args)
    plans = []
    for row in rows:
        urls = resolved.get(row.id)
        if not urls:
            summary["missing_from_provider"] += 1
            continue
        plan = plan_row(row, urls, source)
        if plan is None:
            summary["missed"] += 1
            continue
        plans.append(plan)
        summary["urls"][str(row.id)] = plan["to_url"]

    for batch in batched(plans, args.batch_size):
        summary["written"] += await apply_plans(session, batch, apply=args.apply)
        if args.apply:
            # One commit per batch: a crash costs this batch, not the run.
            await session.commit()

    summary["resolved"] = len(plans)
    logger.info(
        "[%s] selected=%d resolved=%d unchanged=%d provider_miss=%d written=%d%s",
        source, summary["selected"], summary["resolved"], summary["missed"],
        summary["missing_from_provider"], summary["written"],
        "" if args.apply else " (dry run)",
    )
    return summary


async def resolve_anilist(rows, args) -> Dict[int, List[str]]:
    """`{manga_id: [cover_url]}` from AniList, respecting the daily request budget."""
    if not rows:
        return {}

    by_anilist: Dict[int, List[Any]] = {}
    for row in rows:
        by_anilist.setdefault(int(row.anilist_id), []).append(row)

    ids = list(by_anilist)
    resolved: Dict[int, List[str]] = {}

    for batch in batched(ids, 50):
        try:
            await consume("anilist", settings.ANILIST_DAILY_REQUEST_BUDGET, spend=args.apply)
        except BudgetExceeded:
            left = await remaining("anilist", settings.ANILIST_DAILY_REQUEST_BUDGET)
            logger.warning(
                "AniList: daily budget spent, stopping this phase (%d id(s) left, %d remaining)",
                len(ids) - len(resolved), left,
            )
            break

        covers = await fetch_covers_by_ids(batch)
        for anilist_id, cover in covers.items():
            urls = [url for url in (cover.get("large"), cover.get("medium")) if url]
            if not urls:
                continue
            for row in by_anilist.get(anilist_id, ()):
                resolved[row.id] = urls

    logger.info("AniList: %d id(s) -> %d with a cover", len(ids), len(resolved))
    return resolved


# --- verification ----------------------------------------------------------


def host_verdict(samples: Sequence[Tuple[bool, str]]) -> str:
    """`up` / `down` / `unknown` for one host, from its sample results.

    The distinction that matters: one failing URL while its neighbours pass is rot.
    *Every* sample failing is a block or an outage, and in that case no row may be
    marked dead - the rows are fine, the host is not.
    """
    if not samples:
        return "unknown"
    successes = sum(1 for ok, _ in samples if ok)
    if successes == 0:
        return "down"
    return "up"


def is_dead(previous_failures: int, this_failure: bool) -> bool:
    """Two strikes on separate runs, never one.

    `previous_failures` counts earlier failed runs recorded in `cover_repair_log`
    inside the window, so a single timeout - or one run repeated twice - cannot
    condemn a row.
    """
    if not this_failure:
        return False
    return (previous_failures + 1) >= VERIFY_STRIKES


async def probe_cover(client: httpx.AsyncClient, url: str) -> Tuple[bool, str]:
    """One cover URL, judged the way a browser would judge it."""
    try:
        response = await client.get(url)
    except Exception as exc:
        return False, f"{type(exc).__name__}"

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if response.status_code == 200 and content_type.startswith("image/"):
        return True, f"200 {content_type}"
    # 200 with an HTML body is the original outage's signature: the status lies.
    return False, f"http {response.status_code} {content_type or 'no content-type'}"


async def sample_host(client: httpx.AsyncClient, source: str, rows: Sequence[Any], semaphore) -> List[Tuple[bool, str]]:
    async def one(row):
        async with semaphore:
            return await probe_cover(client, row.cover_image_url)

    return list(await asyncio.gather(*(one(row) for row in rows)))


async def breaker_open(host: str) -> bool:
    try:
        return bool(await redis_client.exists(VERIFY_BREAKER_KEY.format(host=host)))
    except Exception:
        return False


async def open_breaker(host: str) -> None:
    try:
        await redis_client.set(VERIFY_BREAKER_KEY.format(host=host), "1", ex=VERIFY_BREAKER_TTL_SECONDS)
    except Exception as exc:
        verify_logger.debug("Could not set the breaker for %s: %s", host, exc)


async def run_verify(session, args) -> Dict[str, Any]:
    """Sample each host, decide host health, then apply the two-strike rule."""
    summary: Dict[str, Any] = {
        "source": "verify", "hosts": [], "dead": 0, "probes": 0, "written": 0, "checked": 0,
    }
    per_host = max(1, args.sample_per_host)
    semaphore = asyncio.Semaphore(VERIFY_CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=VERIFY_TIMEOUT, headers=VERIFY_BROWSER_HEADERS, follow_redirects=True
    ) as client:
        for host in VERIFY_HOSTS:
            if await breaker_open(host):
                verify_logger.info("%s skipped: breaker open after a recent failure", host)
                summary["hosts"].append({"host": host, "verdict": "skipped", "sampled": 0})
                continue

            rows = (
                await session.execute(
                    text(VERIFY_SAMPLE_SQL), {"prefix": f"https://{host}/%", "sample": per_host}
                )
            ).all()
            if not rows:
                summary["hosts"].append({"host": host, "verdict": "empty", "sampled": 0})
                continue

            samples = await sample_host(client, host, rows, semaphore)
            summary["probes"] += len(samples)
            verdict = host_verdict(samples)
            failures = [row for row, (ok, _) in zip(rows, samples) if not ok]
            ok_count = len(samples) - len(failures)

            verify_logger.info(
                "%s: %d/%d ok -> host %s", host, ok_count, len(samples), verdict
            )
            summary["hosts"].append(
                {"host": host, "verdict": verdict, "sampled": len(samples), "ok": ok_count}
            )

            if verdict == "down":
                # Every sample failed: treat it as the host, not the rows.
                await open_breaker(host)
                verify_logger.warning(
                    "%s answered 0/%d samples (%s); breaker open for %dh, "
                    "no rows marked dead",
                    host, len(samples), samples[0][1] if samples else "-",
                    VERIFY_BREAKER_TTL_SECONDS // 3600,
                )
                continue

            # The host is up, so any individual failure is real rot. Strike one is
            # recorded and costs nothing; a second failure in the window marks the
            # row dead.
            prior: Dict[int, int] = {}
            if failures:
                prior = dict(
                    (
                        await session.execute(
                            text(VERIFY_STRIKES_SQL),
                            {
                                "days": VERIFY_FAILURE_WINDOW_DAYS,
                                "ids": [row.id for row in failures],
                            },
                        )
                    ).all()
                )

            by_id = {row.id: (ok, detail) for row, (ok, detail) in zip(rows, samples)}
            to_dead: List[int] = []
            to_log: List[CoverRepairLog] = []
            for row in failures:
                detail = by_id[row.id][1]
                previous = int(prior.get(row.id, 0))
                dead = is_dead(previous, True)
                to_log.append(
                    CoverRepairLog(
                        manga_id=row.id,
                        from_url=row.cover_image_url,
                        to_url=None,
                        source="none",
                        result="failed",
                        detail=f"{host}: {detail} (strike {previous + 1}/{VERIFY_STRIKES})",
                    )
                )
                if dead:
                    to_dead.append(row.id)
                verify_logger.debug(
                    "Row %s failed %s (strike %d/%d)%s",
                    row.id, detail, previous + 1, VERIFY_STRIKES, " -> dead" if dead else "",
                )

            checked_ids = [row.id for row in rows]
            summary["dead"] += len(to_dead)
            summary["checked"] += len(checked_ids)

            if not args.apply:
                continue

            # Every sampled row gets "checked just now", whether it passed or not:
            # that timestamp is what makes a stale verdict visible later.
            if to_log:
                session.add_all(to_log)
            if checked_ids:
                await session.execute(
                    update(Manga)
                    .where(Manga.id.in_(checked_ids))
                    .values(cover_checked_at=datetime.now(timezone.utc))
                )
            if to_dead:
                await session.execute(
                    update(Manga).where(Manga.id.in_(to_dead)).values(cover_status="dead")
                )
            await session.commit()
            summary["written"] += len(to_dead)
            if to_dead:
                verify_logger.warning("%s: %d row(s) marked dead", host, len(to_dead))

    if args.apply:
        # `cover_checked_at` was backfilled by a migration, so it cannot prove a run
        # happened. This key can, and cover health reads it.
        try:
            await redis_client.set(
                VERIFY_LAST_RUN_KEY,
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "probes": summary["probes"],
                        "checked": summary["checked"],
                        "dead": summary["dead"],
                        "hosts": {h["host"]: h["verdict"] for h in summary["hosts"]},
                    }
                ),
                ex=90 * 24 * 3600,
            )
        except Exception as exc:
            verify_logger.debug("Could not record the run: %s", exc)
    else:
        await session.rollback()
    verify_logger.info(
        "%d probe(s), %d row(s) checked, %d marked dead%s",
        summary["probes"], summary["checked"], summary["dead"],
        "" if args.apply else " (dry run)",
    )
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Re-source dead manga covers.")
    parser.add_argument(
        "--mode", choices=("repair", "second-candidate", "verify"), default="repair",
        help="repair dead covers (default), add a fallback to healthy ones, or spot-check",
    )
    parser.add_argument("--source", choices=("tenrai", "anilist", "both"), default="both")
    parser.add_argument("--limit", type=int, default=None, help="max rows per source")
    parser.add_argument("--batch-size", type=int, default=500, help="rows per commit")
    parser.add_argument(
        "--min-popularity", type=int, default=None,
        help="only repair titles at or above this popularity",
    )
    parser.add_argument(
        "--sample-per-host", type=int, default=VERIFY_SAMPLE_PER_HOST,
        help="verify mode: how many cover URLs to probe per host",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="write the changes (default: rehearsal, provider requests are still made)",
    )
    return parser.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    # The project's log configuration, not `basicConfig`: it silences the transport
    # libraries (`httpx` logged every one of the 60 probes at INFO and buried the
    # summary), and it honours LOG_LEVEL / LOG_FORMAT. Logs go to stderr so stdout is
    # only the report a caller might parse.
    from app.core.logging import configure_logging

    configure_logging(stream=sys.stderr)

    started = time.monotonic()
    run: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "apply": args.apply,
        "mode": args.mode,
        "limit": args.limit,
        "min_popularity": args.min_popularity,
        "phases": [],
    }

    if args.mode == "verify":
        async with AsyncSessionLocal() as session:
            run["phases"].append(await run_verify(session, args))
        run["anilist_budget_remaining"] = await remaining(
            "anilist", settings.ANILIST_DAILY_REQUEST_BUDGET
        )
        return await finish_run(run, args, started)

    if args.mode == "second-candidate" and args.source == "anilist":
        # AniList is already the primary for every healthy row, so it cannot add a
        # fallback - and the budget is better spent on repaired covers.
        logger.error("--mode second-candidate works with --source tenrai only")
        return 2

    phases = [
        ("tenrai", TENRAI_SQL, resolve_tenrai),
        ("anilist", ANILIST_SQL, resolve_anilist),
    ]
    if args.mode == "second-candidate":
        phases = [("tenrai", SECOND_CANDIDATE_SQL, resolve_tenrai)]

    async with AsyncSessionLocal() as session:
        for source, sql, resolver in phases:
            if source not in ("tenrai", "anilist"):
                continue
            if args.source != "both" and args.source != source:
                continue
            run["phases"].append(await run_phase(session, sql, args, resolver, source))

        if not args.apply:
            await session.rollback()
        run["anilist_budget_remaining"] = await remaining(
            "anilist", settings.ANILIST_DAILY_REQUEST_BUDGET
        )

    return await finish_run(run, args, started)


async def finish_run(run: Dict[str, Any], args, started: float) -> int:
    """Report, persist the run summary, and print the human summary."""
    written = sum(phase["written"] for phase in run["phases"])
    if args.apply and written:
        run["cache_keys_cleared"] = await invalidate_catalog_caches()

    run["duration_s"] = round(time.monotonic() - started, 1)
    run["total_written"] = written

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(LAST_RUN_FILE, "w", encoding="utf-8") as handle:
        json.dump(run, handle, indent=2)
    with open(RUNS_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(run) + "\n")

    for phase in run["phases"]:
        if phase["source"] == "verify":
            for host in phase["hosts"]:
                print(
                    f"   {host['host']:<26} {host['verdict']:<8} "
                    f"{host.get('ok', 0)}/{host['sampled']} ok"
                )
            print(
                f"   probes={phase['probes']}  checked={phase['checked']}  "
                f"marked_dead={phase['dead']}"
            )
            continue
        print(
            f"{phase['source']:>8}: selected={phase['selected']:<6} "
            f"resolved={phase['resolved']:<6} provider_miss={phase['missing_from_provider']:<6} "
            f"written={phase['written']}"
        )
    print(
        f"\n{'APPLIED' if args.apply else 'DRY RUN'}: {written} row(s) in {run['duration_s']}s; "
        f"anilist budget remaining today: {run['anilist_budget_remaining']}"
    )
    if not args.apply:
        print("nothing was written; re-run with --apply")
    print(f"report: {LAST_RUN_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
