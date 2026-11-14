import pytest
from sqlalchemy import func, select, text

from app.db import AsyncSessionLocal
from app.db_models import Manga, MangaExternalId
from app.ingestion.upsert import smart_upsert_manga_ex
from app.sync.identity import normalize_external_id
from app.sync.schema import seed_external_ids, verify_schema

TEST_IDS = {
    "anilist": 9_999_9701,
    "mal": 9_999_9702,
    "anilist_b": 9_999_9703,
    "mal_b": 9_999_9704,
    "mangadex": "sync-test-99999705",
}


async def _cleanup():
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                DELETE FROM manga
                WHERE anilist_id = ANY(:anilist_ids)
                   OR mal_id = ANY(:mal_ids)
                   OR mangadex_id = :mangadex_id
                """
            ),
            {
                "anilist_ids": [TEST_IDS["anilist"], TEST_IDS["anilist_b"]],
                "mal_ids": [TEST_IDS["mal"], TEST_IDS["mal_b"]],
                "mangadex_id": TEST_IDS["mangadex"],
            },
        )
        await session.commit()


@pytest.fixture
async def sync_schema():
    await verify_schema()
    await _cleanup()
    yield
    await _cleanup()


def test_external_id_normalization():
    assert normalize_external_id("anilist", " 123 ") == "123"
    assert normalize_external_id("mangadex", "ABC-DEF") == "abc-def"
    assert normalize_external_id("mal", 0) is None
    assert normalize_external_id("anilist", "not-a-number") is None


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_writes_mapping(sync_schema):
    record = {
        "anilist_id": TEST_IDS["anilist"],
        "mal_id": TEST_IDS["mal"],
        "title_romaji": "Sync Identity Test",
        "title_english": "Sync Identity Test",
        "start_year": 2097,
        "synopsis": "A test record for the sync identity map.",
        "genres": ["Action"],
        "tags": [{"name": "Test", "rank": 50}],
    }

    async with AsyncSessionLocal() as session:
        first = await smart_upsert_manga_ex(session, record)
        await session.commit()
        manga_id = first.manga.id
        assert first.action == "inserted"

        count = await session.scalar(
            select(func.count()).select_from(Manga).where(Manga.anilist_id == TEST_IDS["anilist"])
        )
        assert count == 1

        mapping_count = await session.scalar(
            select(func.count()).select_from(MangaExternalId).where(
                MangaExternalId.source == "anilist",
                MangaExternalId.external_id == str(TEST_IDS["anilist"]),
            )
        )
        assert mapping_count == 1

        second = await smart_upsert_manga_ex(session, record)
        await session.commit()

        assert second.manga.id == manga_id
        assert second.action == "unchanged"
        count = await session.scalar(
            select(func.count()).select_from(Manga).where(Manga.anilist_id == TEST_IDS["anilist"])
        )
        assert count == 1


@pytest.mark.asyncio
async def test_cross_id_conflict_does_not_insert_or_move_ids(sync_schema):
    async with AsyncSessionLocal() as session:
        session.add(Manga(
            anilist_id=TEST_IDS["anilist_b"],
            title_romaji="Sync Conflict A",
            title_english="Sync Conflict A",
            start_year=2096,
        ))
        session.add(Manga(
            mal_id=TEST_IDS["mal_b"],
            title_romaji="Sync Conflict B",
            title_english="Sync Conflict B",
            start_year=2096,
        ))
        await session.commit()
        await seed_external_ids()

        before = await session.scalar(select(func.count()).select_from(Manga))

        result = await smart_upsert_manga_ex(session, {
            "anilist_id": TEST_IDS["anilist_b"],
            "mal_id": TEST_IDS["mal_b"],
            "title_romaji": "Sync Conflict A",
            "title_english": "Sync Conflict A",
            "start_year": 2096,
        })
        await session.commit()

        after = await session.scalar(select(func.count()).select_from(Manga))
        assert after == before
        assert result.manga.anilist_id == TEST_IDS["anilist_b"]
        assert result.manga.mal_id != TEST_IDS["mal_b"]
        assert any(c["source"] == "mal" and c["external_id"] == str(TEST_IDS["mal_b"]) for c in result.conflicts)
