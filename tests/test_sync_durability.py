"""Stage 2: the sync loop must not lose work it has already paid for.

Four holes, one test file:

* PIPE-06 — a record stamped exactly at the checkpoint used to be skipped by
  `updated <= checkpoint`, so a run that stopped mid-page could never pick it up.
* PIPE-08 — identity resolution cost ~11 round trips per record; the column probe
  and the follow-up re-read of the same rows are now one statement.
* PIPE-05 — the MangaDex link write sat outside the per-row try, so one bad row
  aborted the page after the cursor had already moved on.
* PIPE-11 — the standalone ingestion script dropped a whole title when a tag was
  malformed or the embedding provider hiccupped, and counted nothing.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, text

from app.db import AsyncSessionLocal, engine
from app.db_models import Manga
from app.ingestion import ingest
from app.sync import service as sync_service
from app.sync.identity import ExternalId, attach_external_ids, find_match
from app.sync.schema import ensure_sync_schema

CHECKPOINT = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def _summary() -> dict:
    return {
        "run_id": "test-run",
        "mode": "manual",
        "dry_run": False,
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


async def _wipe(*anilist_ids: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM manga WHERE anilist_id = ANY(:ids)"), {"ids": list(anilist_ids)}
        )
        await session.commit()


@pytest.fixture
async def sync_schema():
    await ensure_sync_schema()
    yield


# --- PIPE-06 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_at_the_checkpoint_is_reprocessed(sync_schema, monkeypatch):
    """The boundary record must reach the writer instead of being counted as done."""
    boundary = {"anilist_id": 9_999_9001, "title_romaji": "Boundary", "source_updated_at": CHECKPOINT}
    applied: list[list[dict]] = []

    async def fake_fetch(page, per_page, **kwargs):
        return {
            "media": [{"id": boundary["anilist_id"]}],
            "pageInfo": {"hasNextPage": False},
        }

    async def fake_apply(records, summary, *, dry_run, generate_embeddings):
        applied.append(list(records))

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "anilist_to_record", lambda raw: dict(boundary))
    monkeypatch.setattr(sync_service, "_apply_anilist_page", fake_apply)
    await sync_service._save_state("anilist", checkpoint_at=CHECKPOINT)

    summary = _summary()
    await sync_service._run_anilist(
        summary, max_pages=1, since=None, dry_run=False, generate_embeddings=False
    )

    assert applied, "the record stamped exactly at the checkpoint was skipped"
    assert applied[0][0]["anilist_id"] == boundary["anilist_id"]
    assert summary["rows_unchanged"] == 0, "the boundary record must not be counted as unchanged"


@pytest.mark.asyncio
async def test_record_older_than_the_checkpoint_is_still_skipped(sync_schema, monkeypatch):
    older = {"anilist_id": 9_999_9002, "title_romaji": "Older", "source_updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc)}
    applied: list[list[dict]] = []

    async def fake_fetch(page, per_page, **kwargs):
        return {"media": [{"id": older["anilist_id"]}], "pageInfo": {"hasNextPage": False}}

    async def fake_apply(records, summary, *, dry_run, generate_embeddings):
        applied.append(list(records))

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "anilist_to_record", lambda raw: dict(older))
    monkeypatch.setattr(sync_service, "_apply_anilist_page", fake_apply)
    await sync_service._save_state("anilist", checkpoint_at=CHECKPOINT)

    summary = _summary()
    await sync_service._run_anilist(
        summary, max_pages=1, since=None, dry_run=False, generate_embeddings=False
    )

    assert applied == []
    assert summary["rows_unchanged"] == 1


# --- PIPE-08 ---------------------------------------------------------------


class _StatementCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)


@pytest.mark.asyncio
async def test_identity_resolution_costs_a_bounded_number_of_queries(sync_schema):
    """A record carrying three provider IDs must not fan out into a query storm."""
    anilist_id, mal_id, mangadex_id = 9_999_9011, 9_999_9012, "md-durability-99999013"
    async with AsyncSessionLocal() as session:
        session.add(
            Manga(
                anilist_id=anilist_id,
                mal_id=mal_id,
                mangadex_id=mangadex_id,
                title_romaji="Query budget",
                title_english="Query budget",
                is_nsfw=False,
            )
        )
        await session.commit()

    counter = _StatementCounter()
    target = engine.sync_engine
    event.listen(target, "before_cursor_execute", counter)
    try:
        async with AsyncSessionLocal() as session:
            record = {"anilist_id": anilist_id + 100, "mal_id": mal_id + 100, "title_romaji": "Query budget"}
            match = await find_match(session, record)
            assert match.manga is None, "the seeded row must not match unrelated IDs"
            await attach_external_ids(session, match.manga.id if match.manga else 1, [
                ExternalId("anilist", str(anilist_id + 100)),
                ExternalId("mal", str(mal_id + 100)),
            ])
            await session.rollback()
    finally:
        event.remove(target, "before_cursor_execute", counter)

    lookup = [
        s for s in counter.statements
        if "manga_external_ids" in s or " FROM manga" in s or "FROM manga " in s
    ]
    # Was ~11 statements per record (one probe per column, one per mapping row,
    # then the same rows re-read). Five is the batched ceiling.
    assert len(lookup) <= 5, f"{len(lookup)} lookups for one record:\n" + "\n".join(lookup)
    await _wipe(anilist_id)


# --- PIPE-05 ---------------------------------------------------------------


async def _seed_linkless(count: int) -> list[int]:
    ids: list[int] = []
    async with AsyncSessionLocal() as session:
        for index in range(count):
            row = Manga(
                title_english=f"Durable {index}",
                title_romaji=f"Durable {index}",
                mangadex_id=f"md-durable-{index}",
                is_nsfw=False,
            )
            session.add(row)
            await session.flush()
            ids.append(row.id)
        await session.commit()
    return ids


@pytest.mark.asyncio
async def test_link_write_failure_keeps_the_cursor_behind_the_failing_row(monkeypatch):
    ids = await _seed_linkless(2)
    await sync_service._save_state("mangadex_links", checkpoint_value="0")

    async def fake_fetch(mangadex_id: str) -> dict:
        return {"id": mangadex_id, "attributes": {"links": {}}}

    calls = {"n": 0}
    real_attach = sync_service.attach_external_ids

    async def flaky_attach(session, manga_id, external_ids, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated write failure on the second row")
        return await real_attach(session, manga_id, external_ids, **kwargs)

    monkeypatch.setattr(sync_service, "fetch_mangadex_detail", fake_fetch)
    monkeypatch.setattr(sync_service, "attach_external_ids", flaky_attach)

    summary = _summary()
    await sync_service._run_mangadex_links(summary, batch_size=10, dry_run=False)

    state = await sync_service._get_state("mangadex_links")
    assert calls["n"] == 2, "the second row should have been attempted"
    assert any("mangadex link write" in error for error in summary["errors"]), summary["errors"]
    # The first row committed, the failing row did not, and the cursor sits
    # between them so the next run retries exactly the row that failed.
    assert int(state.checkpoint_value) == ids[0], (
        f"cursor moved to {state.checkpoint_value}, expected {ids[0]}"
    )
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM manga WHERE id = ANY(:ids)"), {"ids": ids})
        await session.commit()


# --- PIPE-11 ---------------------------------------------------------------


def test_tag_extraction_survives_malformed_tags():
    record = {"tags": [{"name": "Action"}, "Comedy", {"no_name": True}, None, 42, {"name": "  "}]}
    assert ingest._tag_names(record) == ["Action", "Comedy"]


@pytest.mark.asyncio
async def test_ingestion_counts_skips_instead_of_dropping_silently(monkeypatch):
    async def no_init_db():
        return None

    async def fake_fetch_page(**kwargs):
        return {
            "media": [
                {"id": 9_999_9021, "format": "MANGA"},
                {"id": None},
            ],
            "pageInfo": {"hasNextPage": False},
        }

    async def failing_embedding(text_to_embed: str) -> list[float]:
        raise RuntimeError("embedding provider is down")

    upserted: list[dict] = []

    async def fake_upsert(session, record):
        upserted.append(record)

    monkeypatch.setattr(ingest, "init_db", no_init_db)
    monkeypatch.setattr(ingest, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(ingest, "generate_embedding", failing_embedding)
    monkeypatch.setattr(ingest, "anilist_to_record", lambda raw: {
        "anilist_id": raw["id"],
        "title_romaji": "Ingested",
        "tags": [{"name": "Action"}],
        "synopsis": "s",
    })
    monkeypatch.setattr(ingest, "upsert_manga", fake_upsert)

    skipped = await ingest.run_ingestion(start_year=2000, end_year=2000)

    assert skipped["invalid"] == 1, "a record without an id must be counted, not ignored"
    assert skipped["embed_failed"] == 1, "a failed embedding must be counted"
    assert len(upserted) == 1, "the title is still worth keeping without a vector"
    assert "embedding" not in upserted[0], "no vector should be stored when embedding failed"
