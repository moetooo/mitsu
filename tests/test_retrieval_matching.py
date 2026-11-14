"""Stage 5B regression tests: the title shortcut, franchise grouping, roulette sampling.

Three measured defects:

* SVC-06 -- `word_similarity >= 0.65` is true whenever one query word appears in a
  title, so 10 of 12 thematic searches were answered with a single obscure title
  ("cooking" -> "Hot-to-Go Bakery: Cooking the Dead").
* SVC-03 -- `apply_diversity_filtering` restored the unfiltered list when every
  row was excluded, so marking titles as already-seen had no effect; and the
  15-character title prefix merged distinct series.
* SVC-01 -- a draw was one contiguous block of primary keys, so a draw came from
  a single ingest batch (76% carried a MangaDex id, against a 14% baseline).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.db import AsyncSessionLocal
from app.services.retrieval import (
    apply_diversity_filtering,
    franchise_key,
    is_confident_title_match,
    sample_candidates_from_db,
)


# ---------------------------------------------------------------------------
# SVC-06 -- deciding whether the query names a title
# ---------------------------------------------------------------------------
def test_exact_title_is_accepted():
    accepted, _ = is_confident_title_match("berserk", "Berserk", 1.0, 1.0)
    assert accepted is True


def test_a_verbatim_word_fragment_is_not_a_title():
    """`cooking` scores word_similarity 1.000 against a title containing it.

    That is the exact case that hijacked 5 of the 12 measured thematic queries.
    """
    accepted, reason = is_confident_title_match(
        "cooking", "Hot-to-Go Bakery: Cooking the Dead", 0.615, 1.000
    )
    assert accepted is False
    assert reason == "verbatim-fragment"


def test_a_misspelling_is_still_accepted():
    """A misspelling cannot appear verbatim, so it keeps the shortcut.

    Without this the semantic fallback recovers only 2 of 8 measured misspellings.
    """
    for query, title, sim, word_sim in [
        ("bersrk", "Berserk", 0.500, 0.571),
        ("death ntoe", "Death Note", 0.467, 0.636),
        ("attack on titen", "Attack on Titan", 0.684, 0.812),
        ("fullmetal alchemst", "Fullmetal Alchemist", 0.773, 0.842),
        ("chainsaw mann", "Chainsaw Man", 0.800, 0.857),
        ("tokyo revenger", "Tokyo Revengers", 0.824, 0.933),
    ]:
        accepted, reason = is_confident_title_match(query, title, sim, word_sim)
        assert accepted is True, f"{query!r} -> {title!r} was rejected as {reason!r}"


def test_a_weak_similarity_is_rejected():
    accepted, reason = is_confident_title_match("a completely different thing", "Berserk", 0.1, 0.2)
    assert accepted is False
    assert reason in ("similarity", "coverage")


def test_a_short_fragment_of_a_long_title_is_rejected():
    """"sports underdog team" -> "Underdog" is a fragment, not a title."""
    accepted, reason = is_confident_title_match("sports underdog team", "Underdog", 0.429, 0.429)
    assert accepted is False
    assert reason in ("coverage", "similarity")


def test_a_missing_title_is_rejected():
    for title in (None, "", "   "):
        accepted, reason = is_confident_title_match("berserk", title, 1.0, 1.0)
        assert accepted is False
        assert reason == "no-title"


def test_the_verbatim_veto_is_configurable():
    """The veto is the structural rule; it must be overridable, and the default
    must sit above every measured misspelling (0.933) and at the fragment value."""
    assert settings.TITLE_MATCH_MAX_WORD_SIM > 0.933
    assert settings.TITLE_MATCH_MAX_WORD_SIM <= 1.0


# ---------------------------------------------------------------------------
# SVC-03 -- grouping repeats of one series
# ---------------------------------------------------------------------------
def test_volume_suffixes_collapse():
    assert franchise_key("Solo Leveling") == franchise_key("Solo Leveling Vol. 2")
    assert franchise_key("Solo Leveling") == franchise_key("Solo Leveling, Vol. 3")


def test_different_series_are_not_merged():
    """The 15-character prefix merged these; they are different series."""
    pairs = [
        ("Berserk", "Berserk of Gluttony"),
        ("One Piece", "One Piece Party"),
        ("Mobile Suit Gundam: The Origin", "Mobile Suit Gundam Thunderbolt"),
        ("The Villainess Flips the Script!", "The Villainess Turns the Hourglass"),
    ]
    for a, b in pairs:
        assert franchise_key(a) != franchise_key(b), f"{a!r} and {b!r} were merged"


def test_a_titleless_row_still_gets_a_distinct_key():
    assert franchise_key(None, 42) == "id:42"
    assert franchise_key("   ", 42) == "id:42"
    assert franchise_key(None, 42) != franchise_key(None, 43)


def _row(row_id, title, average_score=75, popularity=5000, genres=("Action",)):
    return SimpleNamespace(
        id=row_id,
        anilist_id=row_id,
        mal_id=None,
        title_english=title,
        title_romaji=None,
        title_native=None,
        cover_image_url="http://example/c.jpg",
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


def test_exclusion_is_absolute():
    """Every row seen -> nothing returned.

    The old code restored the full list in this case, which made `exclude_ids` a
    no-op at exactly the moment a user had seen everything.
    """
    rows = [_row(i, f"Title {i}", genres=("Action",)) for i in range(1, 21)]
    assert apply_diversity_filtering(rows, exclude_ids={r.id for r in rows}, max_target=10) == []


def test_already_seen_titles_never_come_back():
    rows = [_row(i, f"Title {i}", genres=(f"Genre{i}",)) for i in range(1, 21)]
    seen = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    out = apply_diversity_filtering(rows, exclude_ids=seen, max_target=10)
    leaked = [item["id"] for item in out if item["id"] in seen]
    assert leaked == [], f"already-seen ids returned: {leaked}"
    assert out, "the ten unseen rows should still be returned"


def test_two_entries_of_different_series_both_survive():
    rows = [_row(1, "Berserk", genres=("Dark Fantasy",)),
            _row(2, "Berserk of Gluttony", genres=("Action",))]
    out = apply_diversity_filtering(rows, exclude_ids=set(), max_target=5)
    assert {item["id"] for item in out} == {1, 2}


def test_one_series_fills_only_one_slot():
    rows = [_row(1, "Solo Leveling", genres=("Action",)),
            _row(2, "Solo Leveling Vol. 2", genres=("Fantasy",)),
            _row(3, "Solo Leveling Vol. 3", genres=("Adventure",))]
    out = apply_diversity_filtering(rows, exclude_ids=set(), max_target=5)
    assert len(out) == 1, "three volumes of one series must not fill three slots"


# ---------------------------------------------------------------------------
# SVC-01 -- roulette sampling must not be one ingest batch
# ---------------------------------------------------------------------------
@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_a_draw_spans_the_catalogue_instead_of_one_block():
    """A contiguous block covers `limit` ids; spread ranges cover most of the table."""
    import random as _random

    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        bounds = (await db.execute(text(
            "SELECT COALESCE(MIN(id),0) lo, COALESCE(MAX(id),0) hi FROM manga"
        ))).one()
        span = int(bounds.hi) - int(bounds.lo)

        rows = await sample_candidates_from_db(db, None, 80)
        if not rows:
            pytest.skip("catalog has no rows with covers")

        covered = max(r.id for r in rows) - min(r.id for r in rows)
        assert covered > span * 0.25, (
            f"a draw covered only ids {covered} of {span}; it is sampling one block again"
        )


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_unfiltered_draws_are_not_all_one_source():
    """76% of a contiguously-sampled draw carried a MangaDex id vs a 14% baseline."""
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        baseline = (await db.execute(text(
            "SELECT avg((mangadex_id IS NOT NULL)::int) FROM manga WHERE cover_image_url IS NOT NULL"
        ))).scalar_one()

        shares = []
        for _ in range(5):
            rows = await sample_candidates_from_db(db, None, 80)
            if not rows:
                pytest.skip("catalog has no rows with covers")
            shares.append(sum(1 for r in rows if r.mangadex_id) / len(rows))

    mean_share = sum(shares) / len(shares)
    assert abs(mean_share - float(baseline)) < 0.30, (
        f"draws carry a MangaDex id {mean_share:.2f} of the time but the catalogue is "
        f"{float(baseline):.2f}; the sample is one ingest batch, not the catalogue"
    )
