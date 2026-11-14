"""Stage 5A regression tests: ANN settings, pool sizing, honest scores, edge freshness.

Three defects, each with a test that fails on the previous behaviour:

* ARCH-09a -- `app/db.py` stopped setting `hnsw.ef_search`, so pgvector ran at its
  default (40) and capped an ordered ANN scan there. Measured on a 95k-row
  catalog, `ORDER BY embedding <=> q LIMIT 100` returned 39 rows.
* ARCH-09b -- `pool_limit` was `min(max(200, (offset+limit)*15), HNSW_EF_SEARCH)`,
  which is exactly 200 for every page, so the offset term never mattered.
* SVC-02 -- roulette reported `average_score / 100` (default 85) as
  `similarity_score`, a community rating sold as a match percentage.
* ARCH-12 -- precomputed `similar_mangas` edges were write-once and read without
  any freshness check.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import RecommendFilters
from app.services.retrieval import (
    apply_ann_settings,
    apply_diversity_filtering,
    compute_pool_limit,
    retrieve_similar_manga,
    similar_edges_are_fresh,
)


# ---------------------------------------------------------------------------
# ARCH-09b -- the candidate pool has to grow with the page, and stay bounded
# ---------------------------------------------------------------------------
def test_pool_limit_grows_with_offset():
    """Every page used to ask for exactly 200 candidates, so deep pages truncated."""
    first = compute_pool_limit(offset=0, limit=20)
    fifth = compute_pool_limit(offset=80, limit=20)
    assert fifth > first, (
        "pool must grow with offset; equal values mean the offset term is inert again"
    )


def test_pool_limit_always_covers_the_requested_page():
    """A pool smaller than offset+limit can never reach the page it is asked for."""
    for page in range(1, 11):
        limit = 20
        offset = (page - 1) * limit
        pool = compute_pool_limit(offset=offset, limit=limit)
        if pool < settings.HNSW_MAX_POOL_LIMIT:
            assert pool >= offset + limit, (
                f"page {page} asks for rows {(offset, offset + limit)} but pool is {pool}"
            )


def test_pool_limit_is_never_below_the_configured_floor():
    assert compute_pool_limit(offset=0, limit=1) >= settings.HNSW_EF_SEARCH


def test_pool_limit_is_bounded():
    """`page=100, limit=50` must not ask for ~75k candidates."""
    assert compute_pool_limit(offset=4950, limit=50) <= settings.HNSW_MAX_POOL_LIMIT


def test_pool_limit_tolerates_degenerate_input():
    assert compute_pool_limit(offset=-10, limit=0) >= 1


# ---------------------------------------------------------------------------
# ARCH-09a -- the settings are actually applied to the session
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ann_settings_are_applied_to_the_transaction():
    """ef_search=40 with iterative_scan off is what truncated the ANN scan."""
    async with AsyncSessionLocal() as db:
        await apply_ann_settings(db, ef_search=200)
        ef = (await db.execute(text("SELECT current_setting('hnsw.ef_search')"))).scalar_one()
        iterative = (
            await db.execute(text("SELECT current_setting('hnsw.iterative_scan')"))
        ).scalar_one()

    assert int(ef) == 200
    assert iterative == settings.HNSW_ITERATIVE_SCAN
    assert iterative != "off", (
        "without iterative_scan a LIMIT larger than ef_search returns fewer rows"
    )


@pytest.mark.asyncio
async def test_ann_settings_are_transaction_local():
    """A pooled connection must not keep one caller's ef_search for the next."""
    # `missing_ok` because on a session that has not touched the `vector` type
    # yet the GUC does not exist at all -- `current_setting` raises
    # `unrecognized configuration parameter`. That laziness is the whole reason
    # these settings cannot be applied in the connect arguments.
    async with AsyncSessionLocal() as db:
        await apply_ann_settings(db, ef_search=500)
        assert int(
            (await db.execute(text("SELECT current_setting('hnsw.ef_search')"))).scalar_one()
        ) == 500
        await db.rollback()

    async with AsyncSessionLocal() as db:
        after = (
            await db.execute(text("SELECT current_setting('hnsw.ef_search', true)"))
        ).scalar_one()

    assert after != "500", "set_config must be transaction-local so it cannot leak"


# ---------------------------------------------------------------------------
# SVC-02 -- no similarity was computed, so none is reported
# ---------------------------------------------------------------------------
def _row(row_id: int, average_score=None, genres=("Action",), popularity=5000):
    return SimpleNamespace(
        id=row_id,
        anilist_id=row_id,
        mal_id=None,
        title_english=f"Title {row_id}",
        title_romaji=None,
        title_native=None,
        cover_image_url="http://example/cover.jpg",
        banner_image=None,
        synopsis=None,
        genres=list(genres),
        tags=[],
        status="FINISHED",
        start_year=2020,
        chapters=10,
        volumes=1,
        average_score=average_score,
        popularity=popularity,
        site_url=None,
        format_type="MANGA",
    )


def test_roulette_does_not_report_a_score_it_did_not_compute():
    rows = [_row(i, average_score=70) for i in range(1, 6)]
    out = apply_diversity_filtering(rows, exclude_ids=set(), max_target=5)

    assert out, "sanity: the fixture must survive diversity filtering"
    for item in out:
        assert item["similarity_score"] is None, (
            "similarity_score must stay unset when no similarity was computed; "
            f"got {item['similarity_score']!r}"
        )


def test_roulette_keeps_the_community_score_as_its_own_field():
    rows = [_row(1, average_score=70), _row(2, average_score=None)]
    out = apply_diversity_filtering(rows, exclude_ids=set(), max_target=5)
    by_id = {item["id"]: item for item in out}

    assert by_id[1]["average_score"] == 70
    assert by_id[2]["average_score"] is None
    for item in out:
        assert item["similarity_score"] is None


def test_unrated_row_no_longer_claims_eighty_five_percent():
    """`average_score or 85` made every unrated MangaDex row claim an 85% match."""
    out = apply_diversity_filtering([_row(1, average_score=None)], exclude_ids=set(), max_target=1)
    assert out[0]["similarity_score"] is None


# ---------------------------------------------------------------------------
# ARCH-12 -- precomputed edges only count while they are fresh
# ---------------------------------------------------------------------------
def _manga_with_edges(written_at):
    return SimpleNamespace(
        similar_mangas=[{"id": 2, "score": 0.9}],
        similarities_computed_at=written_at,
    )


def test_edges_without_a_timestamp_are_not_fresh():
    assert similar_edges_are_fresh(_manga_with_edges(None)) is False


def test_edges_without_any_neighbours_are_not_fresh():
    manga = SimpleNamespace(similar_mangas=None, similarities_computed_at=datetime.now(timezone.utc))
    assert similar_edges_are_fresh(manga) is False
    manga.similar_mangas = []
    assert similar_edges_are_fresh(manga) is False


def test_recent_edges_are_fresh():
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    assert similar_edges_are_fresh(_manga_with_edges(recent)) is True


def test_edges_past_the_window_are_stale():
    old = datetime.now(timezone.utc) - timedelta(days=settings.SIMILAR_EDGES_MAX_AGE_DAYS + 1)
    assert similar_edges_are_fresh(_manga_with_edges(old)) is False


def test_naive_timestamps_are_interpreted_as_utc():
    """The column is timestamptz, but a tz-naive value must not raise."""
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    assert similar_edges_are_fresh(_manga_with_edges(naive)) is True


def test_a_zero_window_disables_the_age_check():
    old = datetime.now(timezone.utc) - timedelta(days=4000)
    assert similar_edges_are_fresh(_manga_with_edges(old), max_age_days=0) is True


# ---------------------------------------------------------------------------
# Integration: the ANN scan must return the page it was asked for
# ---------------------------------------------------------------------------
@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_ann_scan_returns_the_requested_page_size():
    """Regression for ARCH-09a: at ef_search=40 a LIMIT of 100 returned 39 rows.

    This is the end-to-end shape of the bug -- `retrieve_similar_manga` asks for
    `limit` rows and silently received about `ef_search`.
    """
    from app.db_models import Manga
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        seed = (
            await db.execute(
                select(Manga).where(Manga.embedding.is_not(None)).limit(1)
            )
        ).scalar_one_or_none()
        if seed is None:
            pytest.skip("catalog has no embeddings")
        embedding = list(seed.embedding)

        results = await retrieve_similar_manga(
            session=db,
            query_embedding=embedding,
            filters=RecommendFilters(nsfw=True),
            limit=100,
            exclude_id=seed.id,
        )

    assert len(results) >= 100, (
        f"asked for 100 neighbours and got {len(results)}; "
        "the ANN scan is being capped by ef_search again"
    )
