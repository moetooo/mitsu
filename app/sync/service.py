from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, text

from ..config import settings
from ..db import AsyncSessionLocal, engine
from ..db_models import Manga, SyncApiUsage, SyncRun, SyncState
from ..ingestion.anilist_client import fetch_updated_page
from ..ingestion.mangadex_client import fetch_detail as fetch_mangadex_detail
from ..ingestion.normalize import anilist_to_record
from ..ingestion.upsert import smart_upsert_manga_ex
from ..services.cache import invalidate_catalog_caches
from ..services.embedding import generate_embedding
from .budget import BudgetExceeded, consume, usage_summary
from .control import auto_state, get_auto_enabled
from .guardrails import (
    GuardrailError,
    backfill_request_limit,
    daily_budget,
    effective_daily_limit,
    guard_status,
    limits_from_usage,
    preflight_trigger,
)
from .identity import ExternalId, attach_external_ids, normalize_external_id
from .schema import ensure_sync_schema, seed_external_ids

logger = logging.getLogger("mitsu.sync.service")

LOCK_NAME = "mitsu_catalog_sync"


class SyncAlreadyRunning(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_updated_at(record: dict[str, Any]) -> datetime | None:
    return _parse_dt(record.get("source_updated_at"))


def _embedding_text(record: dict[str, Any]) -> str:
    tags = [t.get("name") for t in (record.get("tags") or []) if isinstance(t, dict)]
    return f"{record.get('synopsis', '') or ''} Tags: {', '.join(t for t in tags if t)}"


async def _create_run(run_id: str, mode: str, dry_run: bool, status: str = "running") -> None:
    async with AsyncSessionLocal() as session:
        session.add(SyncRun(
            run_id=run_id,
            mode=mode,
            status=status,
            dry_run=dry_run,
            request_usage={},
            details={},
        ))
        await session.commit()


async def _finish_run(run_id: str, status: str, summary: dict[str, Any], error: str | None = None) -> None:
    async with AsyncSessionLocal() as session:
        run = await session.scalar(select(SyncRun).where(SyncRun.run_id == run_id))
        if run is None:
            return
        run.status = status
        run.finished_at = _utcnow()
        run.error = error
        run.pages_fetched = int(summary.get("pages_fetched", 0))
        run.rows_seen = int(summary.get("rows_seen", 0))
        run.rows_inserted = int(summary.get("rows_inserted", 0))
        run.rows_updated = int(summary.get("rows_updated", 0))
        run.rows_unchanged = int(summary.get("rows_unchanged", 0))
        run.rows_embedded = int(summary.get("rows_embedded", 0))
        run.rows_conflicted = int(summary.get("rows_conflicted", 0))
        run.request_usage = summary.get("request_usage", {})
        run.details = summary
        await session.commit()


async def _prune_runs() -> None:
    cutoff = _utcnow() - timedelta(days=max(1, settings.SYNC_RUN_RETENTION_DAYS))
    usage_cutoff = _utcnow() - timedelta(days=max(1, settings.SYNC_USAGE_RETENTION_DAYS))
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SyncRun).where(SyncRun.started_at < cutoff))
        await session.execute(delete(SyncApiUsage).where(SyncApiUsage.day < usage_cutoff.date()))
        await session.commit()


async def _get_state(source: str) -> SyncState | None:
    async with AsyncSessionLocal() as session:
        return await session.get(SyncState, source)


async def _save_state(source: str, **values: Any) -> None:
    async with AsyncSessionLocal() as session:
        state = await session.get(SyncState, source)
        if state is None:
            state = SyncState(source=source)
            session.add(state)
        for key, value in values.items():
            setattr(state, key, value)
        state.updated_at = _utcnow()
        await session.commit()


async def _acquire_lock(conn) -> bool:
    value = await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": settings.SYNC_LOCK_KEY})
    return bool(value)


async def _release_lock(conn) -> None:
    try:
        await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": settings.SYNC_LOCK_KEY})
    except Exception:
        logger.warning("Could not release sync advisory lock", exc_info=True)


async def _run_anilist(
    summary: dict[str, Any],
    *,
    max_pages: int,
    since: datetime | None,
    dry_run: bool,
    generate_embeddings: bool,
) -> None:
    state = await _get_state("anilist")
    start_checkpoint = since or (state.checkpoint_at if state else None)
    oldest_saved = start_checkpoint
    await _save_state("anilist", last_attempt_at=_utcnow())

    page = 1
    while page <= max_pages:
        try:
            async def consume_one() -> int:
                # A dry run checks the budget but must not spend it.
                return await consume(
                    "anilist", settings.ANILIST_DAILY_REQUEST_BUDGET, spend=not dry_run
                )

            data = await fetch_updated_page(
                page,
                settings.ANILIST_SYNC_PAGE_SIZE,
                max_retries=2,
                before_request=consume_one,
            )
        except BudgetExceeded as exc:
            logger.warning("AniList sync stopped: %s", exc)
            summary["errors"].append(str(exc))
            break
        except Exception as exc:
            logger.warning("AniList page %d failed: %s", page, exc, exc_info=True)
            summary["errors"].append(f"anilist page {page}: {exc}")
            await _save_state("anilist", last_error=str(exc))
            break

        items = data.get("media") or []
        summary["pages_fetched"] += 1
        if not items:
            break

        page_newest: datetime | None = None
        page_oldest: datetime | None = None
        page_records: list[dict[str, Any]] = []
        for raw in items:
            record = anilist_to_record(raw)
            updated = _record_updated_at(record)
            if updated and (page_newest is None or updated > page_newest):
                page_newest = updated
            # Strictly older than the checkpoint is known work. A record stamped
            # exactly AT the checkpoint may be the one the previous run did not
            # reach before it stopped, so it is processed again; the upsert is
            # idempotent and reports it as unchanged if nothing moved.
            if start_checkpoint and updated and updated < start_checkpoint:
                summary["rows_unchanged"] += 1
                continue
            if updated and (page_oldest is None or updated < page_oldest):
                page_oldest = updated
            page_records.append(record)

        summary["rows_seen"] += len(items)
        if page_records:
            await _apply_anilist_page(
                page_records,
                summary,
                dry_run=dry_run,
                generate_embeddings=generate_embeddings,
            )

        # Use the OLDEST processed update as the watermark. With UPDATED_AT_DESC,
        # taking the newest would skip the pages we did not fetch this run.
        if page_oldest and (oldest_saved is None or page_oldest > oldest_saved):
            oldest_saved = page_oldest

        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        if start_checkpoint and page_newest and page_newest <= start_checkpoint:
            break
        page += 1

    if not dry_run and oldest_saved and (start_checkpoint is None or oldest_saved > start_checkpoint):
        await _save_state(
            "anilist",
            checkpoint_at=oldest_saved,
            checkpoint_value=str(int(oldest_saved.timestamp())),
            last_success_at=_utcnow(),
            last_error=None,
        )

    if summary["errors"]:
        summary["details"]["anilist_usage"] = await usage_summary(
            "anilist", settings.ANILIST_DAILY_REQUEST_BUDGET
        )


async def _apply_anilist_page(
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    dry_run: bool,
    generate_embeddings: bool,
) -> None:
    before = {
        key: summary[key]
        for key in ("rows_inserted", "rows_updated", "rows_unchanged", "rows_embedded", "rows_conflicted")
    }
    async with AsyncSessionLocal() as session:
        try:
            for record in records:
                result = await smart_upsert_manga_ex(session, record)

                if result.conflicts:
                    summary["rows_conflicted"] += len(result.conflicts)
                    for conflict in result.conflicts[:20]:
                        summary["details"].setdefault("conflicts", []).append(conflict)

                if result.inserted:
                    summary["rows_inserted"] += 1
                elif result.content_changed:
                    summary["rows_updated"] += 1
                else:
                    summary["rows_unchanged"] += 1

                if generate_embeddings and (result.inserted or result.content_changed or result.manga.embedding is None):
                    try:
                        result.manga.embedding = await generate_embedding(_embedding_text(record))
                        result.manga.similar_mangas = None
                        result.manga.similarities_computed_at = None
                        summary["rows_embedded"] += 1
                    except Exception as exc:
                        logger.warning("Embedding failed for AniList %s: %s", record.get("anilist_id"), exc)
                        summary["errors"].append(f"embedding anilist {record.get('anilist_id')}: {exc}")

            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        except Exception as exc:
            await session.rollback()
            for key, value in before.items():
                summary[key] = value
            logger.warning("AniList page write failed: %s", exc, exc_info=True)
            summary["errors"].append(f"anilist write: {exc}")
            raise


def _mangadex_link_ids(links: dict[str, Any] | None) -> list[ExternalId]:
    if not links:
        return []
    source_map = {
        "al": "anilist",
        "mal": "mal",
        "kt": "kitsu",
        "mu": "mangaupdates",
        "bgm": "bangumi",
    }
    found: list[ExternalId] = []
    for key, source in source_map.items():
        ext = normalize_external_id(source, links.get(key))
        if ext:
            found.append(ExternalId(source, ext))
    return found


async def _run_mangadex_links(
    summary: dict[str, Any],
    *,
    batch_size: int,
    dry_run: bool,
) -> None:
    state = await _get_state("mangadex_links")
    cursor = int(state.checkpoint_value) if state and state.checkpoint_value else 0
    await _save_state("mangadex_links", last_attempt_at=_utcnow())

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Manga)
            .where(
                Manga.mangadex_id.isnot(None),
                or_(Manga.anilist_id.is_(None), Manga.mal_id.is_(None)),
                Manga.id > cursor,
            )
            .order_by(Manga.id)
            .limit(batch_size)
        )).scalars().all()

        if not rows:
            summary["details"]["mangadex_links"] = {"cursor": cursor, "processed": 0}
            return

        processed = 0
        last_id = cursor
        for row in rows:
            try:
                await consume(
                    "mangadex", settings.MANGADEX_DAILY_REQUEST_BUDGET, spend=not dry_run
                )
            except BudgetExceeded as exc:
                summary["errors"].append(str(exc))
                break

            try:
                raw = await fetch_mangadex_detail(row.mangadex_id)
            except Exception as exc:
                logger.warning("MangaDex link fetch failed for %s: %s", row.mangadex_id, exc)
                summary["errors"].append(f"mangadex {row.mangadex_id}: {exc}")
                last_id = row.id
                processed += 1
                continue

            links = (raw.get("attributes") or {}).get("links") or {}
            ids = _mangadex_link_ids(links)
            ids.append(ExternalId("mangadex", row.mangadex_id))

            # The write sits in a savepoint so a failure here costs one row, not
            # the page: the savepoint rolls back, the cursor stays behind this
            # row, and the next run retries it instead of walking past it.
            try:
                async with session.begin_nested():
                    conflicts = await attach_external_ids(session, row.id, ids)
                    blocked = {(c["source"], c["external_id"]) for c in conflicts}
                    if conflicts:
                        summary["rows_conflicted"] += len(conflicts)
                        for conflict in conflicts[:20]:
                            summary["details"].setdefault("conflicts", []).append(conflict)

                    al = normalize_external_id("anilist", links.get("al"))
                    mal = normalize_external_id("mal", links.get("mal"))
                    if al and row.anilist_id is None and ("anilist", al) not in blocked:
                        row.anilist_id = int(al)
                        row.sync_source = "mangadex"
                        summary["rows_updated"] += 1
                    if mal and row.mal_id is None and ("mal", mal) not in blocked:
                        row.mal_id = int(mal)
                        row.sync_source = "mangadex"
                        summary["rows_updated"] += 1
                    row.last_synced_at = _utcnow()
            except Exception as exc:
                # Read the id before expiring: the failure already invalidated the
                # row's state, and touching an expired attribute here would need
                # IO from a sync context.
                mangadex_id = row.mangadex_id
                logger.warning("MangaDex link write failed for %s: %s", mangadex_id, exc, exc_info=True)
                summary["errors"].append(f"mangadex link write {mangadex_id}: {exc}")
                session.expire_all()
                break

            last_id = row.id
            processed += 1
            summary["rows_seen"] += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        summary["details"]["mangadex_links"] = {
            "cursor": last_id,
            "processed": processed,
        }

    if not dry_run and last_id > cursor:
        await _save_state(
            "mangadex_links",
            checkpoint_value=str(last_id),
            last_success_at=_utcnow(),
            last_error=None,
        )


async def run_sync(
    *,
    mode: str = "manual",
    dry_run: bool = False,
    max_pages: int | None = None,
    since: str | datetime | None = None,
    include_anilist: bool = True,
    include_mangadex: bool | None = None,
    generate_embeddings: bool | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run one idempotent catalog refresh.

    A PostgreSQL advisory lock guarantees one run at a time across processes.
    The function never raises for expected failures; callers get a summary with
    `status` and `errors`, which the CLI turns into an exit code.
    """
    run_id = run_id or str(uuid.uuid4())
    if include_mangadex is None:
        include_mangadex = settings.MANGADEX_SYNC_ENABLED
    if generate_embeddings is None:
        generate_embeddings = settings.SYNC_EMBEDDINGS
    pages = max_pages or settings.ANILIST_SYNC_MAX_PAGES
    since_dt = _parse_dt(since) if since is not None else None

    summary: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "dry_run": dry_run,
        "status": "running",
        "pages_fetched": 0,
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_unchanged": 0,
        "rows_embedded": 0,
        "rows_conflicted": 0,
        "request_usage": {},
        "details": {},
        "errors": [],
    }

    auto_enabled = await get_auto_enabled()
    if not settings.SYNC_ENABLED or (mode == "auto" and not auto_enabled):
        reason = (
            "sync disabled by configuration"
            if not settings.SYNC_ENABLED
            else "auto sync is turned off"
        )
        summary["status"] = "skipped"
        summary["errors"].append(reason)
        summary["details"]["auto_enabled"] = auto_enabled
        await _create_run(run_id, mode, dry_run)
        await _finish_run(run_id, "skipped", summary, reason)
        return summary

    try:
        await ensure_sync_schema()
        await seed_external_ids()
    except Exception as exc:
        summary["status"] = "failed"
        summary["errors"].append(f"schema: {exc}")
        logger.exception("Could not prepare sync schema")
        return summary

    try:
        guard = await preflight_trigger(mode)
    except GuardrailError as exc:
        summary["status"] = "rejected"
        summary["errors"].append(str(exc))
        summary["details"]["guardrail"] = exc.as_dict()
        await _create_run(run_id, mode, dry_run, status="rejected")
        await _finish_run(run_id, "rejected", summary, str(exc))
        return summary
    summary["details"]["guardrail"] = guard
    pages = min(max(1, pages), max(1, int(guard.get("max_pages") or pages)))

    async with engine.connect() as lock_conn:
        if not await _acquire_lock(lock_conn):
            summary["status"] = "skipped"
            summary["errors"].append("another sync is already running")
            await _create_run(run_id, mode, dry_run)
            await _finish_run(run_id, "skipped", summary, "another sync is already running")
            return summary

        try:
            await _create_run(run_id, mode, dry_run)
            if include_anilist:
                await _run_anilist(
                    summary,
                    max_pages=max(1, pages),
                    since=since_dt,
                    dry_run=dry_run,
                    generate_embeddings=generate_embeddings,
                )
            if include_mangadex:
                await _run_mangadex_links(
                    summary,
                    batch_size=settings.MANGADEX_SYNC_BATCH_SIZE,
                    dry_run=dry_run,
                )

            changed = (
                summary["rows_inserted"] + summary["rows_updated"] + summary["rows_embedded"]
            ) > 0
            if changed and not dry_run and settings.SYNC_INVALIDATE_CACHE:
                deleted = await invalidate_catalog_caches()
                summary["details"]["cache_keys_deleted"] = deleted

            summary["request_usage"] = {
                "anilist": await usage_summary("anilist", effective_daily_limit("anilist")),
                "mangadex": await usage_summary("mangadex", effective_daily_limit("mangadex")),
            }
            if summary["errors"]:
                summary["status"] = "partial" if changed else "failed"
            else:
                summary["status"] = "success"
            await _prune_runs()
        except Exception as exc:
            summary["status"] = "failed"
            summary["errors"].append(str(exc))
            logger.exception("Sync run failed")
        finally:
            try:
                await _finish_run(run_id, summary["status"], summary, "; ".join(summary["errors"]) or None)
            finally:
                await _release_lock(lock_conn)

    return summary


async def sync_status(limit: int = 5, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))
    async with AsyncSessionLocal() as session:
        states = (await session.execute(select(SyncState).order_by(SyncState.source))).scalars().all()
        runs_total = int(await session.scalar(select(func.count()).select_from(SyncRun)) or 0)
        runs = (await session.execute(
            select(SyncRun)
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .offset(offset)
            .limit(limit)
        )).scalars().all()
        latest_backfill_details = await session.scalar(
            select(SyncRun.details)
            .where(SyncRun.mode == "backfill", SyncRun.status == "success")
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )

    backfill_state = next((state for state in states if state.source == "anilist_backfill"), None)
    backfill_value = backfill_state.checkpoint_value if backfill_state else None
    backfill_complete = backfill_value == "complete"
    next_page: int | None = None
    if backfill_value and backfill_value.isdigit():
        next_page = int(backfill_value)

    now = _utcnow()
    cutoff_dt = _parse_dt(settings.SYNC_BACKFILL_CUTOFF)
    progress_at = backfill_state.progress_at if backfill_state else None
    if progress_at is None and latest_backfill_details:
        # Older runs predate the progress_at column; their summary still has it.
        latest_backfill = (latest_backfill_details.get("details") or {}).get("backfill") or {}
        progress_at = _parse_dt(latest_backfill.get("oldest_page_at"))
    else:
        latest_backfill = {}
    total_pages = backfill_state.page_total if backfill_state else None
    if total_pages is None and latest_backfill.get("last_page"):
        total_pages = int(latest_backfill["last_page"])
    pages_done = max(0, next_page - 1) if next_page else 0

    if backfill_complete:
        backfill_percent = 100.0
        progress_basis = "complete"
    elif total_pages:
        backfill_percent = round(min(100.0, max(0.0, pages_done / total_pages * 100)), 1)
        progress_basis = "pages"
    elif cutoff_dt and now > cutoff_dt:
        covered = (now - (progress_at or now)).total_seconds()
        total = (now - cutoff_dt).total_seconds()
        backfill_percent = round(min(100.0, max(0.0, covered / total * 100)), 1)
        progress_basis = "time"
    else:
        backfill_percent = 0.0
        progress_basis = "time"
    remaining_days: float | None = None
    if not backfill_complete and cutoff_dt:
        end = progress_at or now
        remaining_days = round(max(0.0, (end - cutoff_dt).total_seconds()) / 86400, 1)

    auto = await auto_state()
    anilist_budget = await usage_summary("anilist", effective_daily_limit("anilist"))
    mangadex_budget = await usage_summary("mangadex", effective_daily_limit("mangadex"))

    return {
        "enabled": settings.SYNC_ENABLED,
        "auto_enabled": bool(auto["enabled"]),
        "auto_source": auto["source"],
        "budgets": {
            "anilist": anilist_budget,
            "mangadex": mangadex_budget,
        },
        "limits": limits_from_usage(anilist_budget),
        "guardrails": await guard_status(),
        "backfill": {
            "complete": backfill_complete,
            "percent": backfill_percent,
            "progress_basis": progress_basis,
            "pages_done": pages_done,
            "total_pages": total_pages,
            "remaining_pages": max(0, total_pages - pages_done) if total_pages else None,
            "cutoff_at": _iso(cutoff_dt),
            "progress_at": _iso(progress_at),
            "remaining_days": remaining_days,
            "checkpoint_value": backfill_value,
            "next_page": next_page,
            "checkpoint_at": _iso(backfill_state.checkpoint_at) if backfill_state else None,
            "last_success_at": _iso(backfill_state.last_success_at) if backfill_state else None,
            "last_attempt_at": _iso(backfill_state.last_attempt_at) if backfill_state else None,
            "last_error": backfill_state.last_error if backfill_state else None,
            "reserve": max(0, int(settings.SYNC_BACKFILL_RESERVE)),
            "limit": backfill_request_limit(),
        },
        "sources": [
            {
                "source": state.source,
                "checkpoint_at": _iso(state.checkpoint_at),
                "checkpoint_value": state.checkpoint_value,
                "last_success_at": _iso(state.last_success_at),
                "last_attempt_at": _iso(state.last_attempt_at),
                "last_error": state.last_error,
            }
            for state in states
        ],
        "runs": [
            {
                "run_id": run.run_id,
                "mode": run.mode,
                "status": run.status,
                "dry_run": run.dry_run,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
                "pages_fetched": run.pages_fetched,
                "rows_seen": run.rows_seen,
                "rows_inserted": run.rows_inserted,
                "rows_updated": run.rows_updated,
                "rows_unchanged": run.rows_unchanged,
                "rows_embedded": run.rows_embedded,
                "rows_conflicted": run.rows_conflicted,
                "request_usage": run.request_usage,
                "error": run.error,
            }
            for run in runs
        ],
        "runs_total": runs_total,
        "runs_offset": offset,
        "has_more": offset + len(runs) < runs_total,
    }


async def _run_anilist_backfill(
    summary: dict[str, Any],
    *,
    until: datetime,
    max_pages: int,
    dry_run: bool,
    generate_embeddings: bool,
    budget_limit: int | None = None,
) -> None:
    """Walk UPDATED_AT_DESC until the cutoff, resuming from a page cursor.

    AniList has no updatedAt range filter, so this is the only way to refresh
    every changed title since a known date. One page of overlap is intentionally
    re-read each run because newly updated titles shift page boundaries.
    """
    state = await _get_state("anilist_backfill")
    if state and state.checkpoint_value == "complete":
        summary["details"]["backfill"] = {"complete": True, "until": _iso(until)}
        summary["status"] = "success"
        return

    limit = budget_limit or settings.ANILIST_DAILY_REQUEST_BUDGET
    cursor = int(state.checkpoint_value) if state and state.checkpoint_value else 1
    page = max(1, cursor - 1)
    await _save_state("anilist_backfill", last_attempt_at=_utcnow())

    reached_cutoff = False
    complete = False
    requests_attempted = 0
    oldest_page_at: datetime | None = None
    last_page: int | None = None
    try:
        for _ in range(max(1, max_pages)):
            async def consume_one() -> int:
                nonlocal requests_attempted
                requests_attempted += 1
                return await consume("anilist", limit, spend=not dry_run)

            try:
                data = await fetch_updated_page(
                    page,
                    settings.ANILIST_SYNC_PAGE_SIZE,
                    max_retries=2,
                    before_request=consume_one,
                )
            except BudgetExceeded as exc:
                summary["errors"].append(
                    f"{exc} after {summary['pages_fetched']} successful pages "
                    f"({requests_attempted} attempts)"
                )
                break
            except Exception as exc:
                summary["errors"].append(f"anilist backfill page {page}: {exc}")
                await _save_state("anilist_backfill", last_error=str(exc))
                break

            items = data.get("media") or []
            page_info = data.get("pageInfo") or {}
            if page_info.get("lastPage"):
                last_page = int(page_info["lastPage"])
            summary["pages_fetched"] += 1
            if not items:
                complete = True
                break

            records = []
            for raw in items:
                record = anilist_to_record(raw)
                updated = _record_updated_at(record)
                if updated and (oldest_page_at is None or updated < oldest_page_at):
                    oldest_page_at = updated
                summary["rows_seen"] += 1
                if updated and updated <= until:
                    reached_cutoff = True
                    continue
                records.append(record)

            if records:
                await _apply_anilist_page(
                    records,
                    summary,
                    dry_run=dry_run,
                    generate_embeddings=generate_embeddings,
                )

            if reached_cutoff:
                complete = True
                break
            if not page_info.get("hasNextPage"):
                complete = True
                break

            page += 1
            if not dry_run:
                values: dict[str, Any] = {
                    "checkpoint_value": str(page),
                    "last_success_at": _utcnow(),
                    "last_error": None,
                }
                if oldest_page_at is not None:
                    values["progress_at"] = oldest_page_at
                if last_page is not None:
                    values["page_total"] = last_page
                await _save_state("anilist_backfill", **values)
    finally:
        summary["details"]["backfill"] = {
            "until": _iso(until),
            "next_page": page,
            "reached_cutoff": reached_cutoff,
            "complete": complete,
            "oldest_page_at": _iso(oldest_page_at),
            "last_page": last_page,
            "requests_attempted": requests_attempted,
            "request_limit": limit,
            "dry_run": dry_run,
        }
        if not dry_run and complete:
            await _save_state(
                "anilist_backfill",
                checkpoint_value="complete",
                checkpoint_at=_utcnow(),
                progress_at=oldest_page_at or until,
                page_total=last_page,
                last_success_at=_utcnow(),
                last_error=None,
            )


async def run_backfill(
    *,
    until: str | datetime | None = None,
    max_pages: int | None = None,
    dry_run: bool = False,
    generate_embeddings: bool | None = None,
    budget_limit: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """One-time, resumable historical refresh from a cutoff to now."""
    run_id = run_id or str(uuid.uuid4())
    until_dt = _parse_dt(until if until is not None else settings.SYNC_BACKFILL_CUTOFF)
    if until_dt is None:
        raise ValueError("invalid backfill cutoff")
    if generate_embeddings is None:
        generate_embeddings = settings.SYNC_EMBEDDINGS
    pages = max_pages or settings.ANILIST_SYNC_MAX_PAGES
    requested_budget = budget_limit
    effective_budget = backfill_request_limit(requested_budget)

    summary: dict[str, Any] = {
        "run_id": run_id,
        "mode": "backfill",
        "dry_run": dry_run,
        "status": "running",
        "pages_fetched": 0,
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_unchanged": 0,
        "rows_embedded": 0,
        "rows_conflicted": 0,
        "request_usage": {},
        "details": {
            "budget": {
                "requested": requested_budget,
                "effective": effective_budget,
                "reserve": max(0, int(settings.SYNC_BACKFILL_RESERVE)),
                "daily": effective_daily_limit("anilist"),
                "hard_ceiling": max(
                    daily_budget("anilist"), int(settings.SYNC_HARD_DAILY_CEILING)
                ),
            }
        },
        "errors": [],
    }

    if not settings.SYNC_ENABLED:
        summary["status"] = "skipped"
        summary["errors"].append("sync disabled by configuration")
        await _create_run(run_id, "backfill", dry_run)
        await _finish_run(run_id, "skipped", summary, "sync disabled by configuration")
        return summary

    try:
        await ensure_sync_schema()
        await seed_external_ids()
    except Exception as exc:
        summary["status"] = "failed"
        summary["errors"].append(f"schema: {exc}")
        return summary

    try:
        guard = await preflight_trigger("backfill")
    except GuardrailError as exc:
        summary["status"] = "rejected"
        summary["errors"].append(str(exc))
        summary["details"]["guardrail"] = exc.as_dict()
        await _create_run(run_id, "backfill", dry_run, status="rejected")
        await _finish_run(run_id, "rejected", summary, str(exc))
        return summary
    summary["details"]["guardrail"] = guard
    effective_budget = min(
        effective_budget, max(0, int(guard.get("max_pages") or effective_budget))
    )
    summary["details"]["budget"]["effective"] = effective_budget
    pages = min(max(1, pages), max(1, int(guard.get("max_pages") or pages)))

    if effective_budget <= 0:
        message = "backfill has no budget left after the daily-sync reserve"
        summary["status"] = "rejected"
        summary["errors"].append(message)
        await _create_run(run_id, "backfill", dry_run, status="rejected")
        await _finish_run(run_id, "rejected", summary, message)
        return summary

    async with engine.connect() as lock_conn:
        if not await _acquire_lock(lock_conn):
            summary["status"] = "skipped"
            summary["errors"].append("another sync is already running")
            await _create_run(run_id, "backfill", dry_run)
            await _finish_run(run_id, "skipped", summary, "another sync is already running")
            return summary

        try:
            await _create_run(run_id, "backfill", dry_run)
            await _run_anilist_backfill(
                summary,
                until=until_dt,
                max_pages=max(1, pages),
                dry_run=dry_run,
                generate_embeddings=generate_embeddings,
                budget_limit=effective_budget,
            )
            changed = (summary["rows_inserted"] + summary["rows_updated"] + summary["rows_embedded"]) > 0
            if changed and not dry_run and settings.SYNC_INVALIDATE_CACHE:
                summary["details"]["cache_keys_deleted"] = await invalidate_catalog_caches()
            summary["request_usage"] = {
                "anilist": await usage_summary("anilist", effective_budget),
            }
            summary["status"] = "partial" if summary["errors"] else "success"
            await _prune_runs()
        except Exception as exc:
            summary["status"] = "failed"
            summary["errors"].append(str(exc))
            logger.exception("Backfill run failed")
        finally:
            try:
                await _finish_run(run_id, summary["status"], summary, "; ".join(summary["errors"]) or None)
            finally:
                await _release_lock(lock_conn)

    return summary
