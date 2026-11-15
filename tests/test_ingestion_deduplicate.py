"""The catalogue cannot hold a duplicate external id, so `run_deduplication` is a no-op.

`app/ingestion/deduplicate.py` merges rows that share an `anilist_id`, `mal_id` or
`mangadex_id` and deletes the loser. It had no test. Reading it against the schema
shows something worth recording: all three columns are `UNIQUE`, so the collision it
is written for cannot be inserted in the first place. The constraint is the real
guard; the merge loop is belt and braces for data written before the constraint
existed.

Two properties are tested here, both cheap and both easy to lose:

1. A duplicate external id is rejected by the database, not silently accepted.
2. On a valid catalogue, deduplication deletes nothing - and it does **not** merge
   two sources for the same title, because it matches on ids only. Merging the same
   work across sources is `app/ingestion/merge.py`, which has its own tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal
from app.db_models import Manga
from app.ingestion.deduplicate import run_deduplication

PREFIX = "Dedupe Probe"


def _row(title: str, **overrides) -> Manga:
    values = dict(
        title_romaji=title,
        title_english=title,
        title_native=title,
        synopsis=f"{title} synopsis.",
        genres=["Action"],
        tags=[{"name": "Action", "rank": 100}],
        status="FINISHED",
        start_year=2020,
        average_score=70,
        popularity=10,
        cover_image_url="https://example.invalid/probe.jpg",
        is_nsfw=False,
    )
    values.update(overrides)
    return Manga(**values)


async def _insert(*rows: Manga) -> list[int]:
    async with AsyncSessionLocal() as session:
        session.add_all(list(rows))
        await session.commit()
        return [row.id for row in rows]


async def _cleanup() -> None:
    from sqlalchemy import delete

    async with AsyncSessionLocal() as session:
        await session.execute(delete(Manga).where(Manga.title_romaji.like(f"{PREFIX}%")))
        await session.commit()


async def _probe_titles() -> list[str]:
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Manga.title_romaji).where(Manga.title_romaji.like(f"{PREFIX}%"))
        )
        return sorted(row for row in result.scalars().all())


@pytest.fixture(autouse=True)
async def clean_probe_rows():
    await _cleanup()
    yield
    await _cleanup()


@pytest.mark.parametrize("column", ["anilist_id", "mal_id", "mangadex_id"])
async def test_a_duplicate_external_id_cannot_be_inserted(column):
    """The constraint, not the merge loop, is what keeps the catalogue clean."""
    value = "probe-dex-1" if column == "mangadex_id" else 900001

    await _insert(_row(f"{PREFIX} First {column}", **{column: value}))

    with pytest.raises(IntegrityError):
        await _insert(_row(f"{PREFIX} Second {column}", **{column: value}))


async def test_deduplication_deletes_nothing_from_a_valid_catalogue():
    ids = await _insert(
        _row(f"{PREFIX} Alpha", anilist_id=900011, mal_id=900011),
        _row(f"{PREFIX} Beta", anilist_id=900012, mal_id=900012, mangadex_id="probe-dex-2"),
    )

    before = await _probe_titles()
    await run_deduplication()
    after = await _probe_titles()

    assert before == after
    assert len(ids) == 2


async def test_the_same_title_from_two_sources_is_not_merged_here():
    """Deduplication matches on ids; a title match alone is not a duplicate.

    Two entries for one work - one from AniList, one from MangaDex - must survive
    this step. Collapsing them is `merge.py`'s decision, made with more evidence.
    """
    await _insert(
        _row(f"{PREFIX} Same Name", anilist_id=900021),
        _row(f"{PREFIX} Same Name", mangadex_id="probe-dex-3"),
    )

    await run_deduplication()

    assert await _probe_titles() == [f"{PREFIX} Same Name", f"{PREFIX} Same Name"]


async def test_rows_without_external_ids_are_left_alone():
    """NULL ids are allowed and are not a collision; several is legitimate."""
    await _insert(
        _row(f"{PREFIX} No Ids A"),
        _row(f"{PREFIX} No Ids B"),
    )

    await run_deduplication()

    assert len(await _probe_titles()) == 2
