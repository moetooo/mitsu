"""Behaviour tests for the cross-source merge pass (QA-17).

The merge pass used to be a raw DELETE, so every tag, synopsis and edge on the
duplicate row was destroyed and anything pointing at it dangled. These tests pin
the replacement contract:

* the plan always resolves a duplicate to one *surviving* row (no chains where a
  row is both survivor and deletion),
* folding a duplicate keeps the union of categorical data and fills gaps only,
* unique id columns move *after* the delete, never during the fold.

They need no database: `build_plan` and the fold helpers are pure.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db_models import Manga
from app.ingestion.merge import (
    _fill_external_id_columns,
    _merge_duplicate_into,
    _merge_similar_edges,
    build_plan,
    clean_title,
    similarity_ratio,
)


def row(**kwargs) -> SimpleNamespace:
    """A stand-in for a Manga row; only the attributes read by the helpers."""
    base = {
        "id": 1,
        "mal_id": None,
        "anilist_id": None,
        "mangadex_id": None,
        "title_romaji": None,
        "title_english": None,
        "start_year": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# build_plan: every duplicate resolves to one survivor
# ---------------------------------------------------------------------------


def test_mal_pair_keeps_the_row_that_has_both_ids():
    rows = [
        row(id=1, mal_id=42, anilist_id=900),
        row(id=2, mal_id=42, anilist_id=None),
    ]

    keep_of, counts = build_plan(rows)

    assert keep_of == {2: 1}
    assert counts == {"mal_id": 1, "title_year": 0, "fuzzy_title": 0}


def test_three_row_chain_collapses_to_the_root_survivor():
    # 3 -> 2 (same mal id, 2 lacks anilist), 2 -> 1: the plan must not leave 2 as
    # both a survivor and a deletion, which would delete the row it points at.
    rows = [
        row(id=1, mal_id=42, anilist_id=900),
        row(id=2, mal_id=42, anilist_id=None, title_english="Shared Title", start_year=2020),
        row(id=3, mal_id=None, anilist_id=None, title_english="shared title", start_year=2020),
    ]

    keep_of, _counts = build_plan(rows)

    assert keep_of == {2: 1, 3: 1}
    assert 1 not in keep_of


def test_title_year_match_is_case_insensitive_and_needs_a_year():
    rows = [
        row(id=1, title_english="Blue Period", start_year=2017),
        row(id=2, title_english="BLUE PERIOD", start_year=2017),
        row(id=3, title_english="Blue Period", start_year=None),
    ]

    keep_of, counts = build_plan(rows)

    assert keep_of == {2: 1}
    assert counts["title_year"] == 1
    # A row with no start_year can never be a title/year duplicate.
    assert 3 not in keep_of


def test_fuzzy_title_matches_only_within_the_same_year():
    same_year = [row(id=1, title_english="Solo Leveling", start_year=2018),
                 row(id=2, title_english="Solo Levelling", start_year=2018)]
    other_year = [row(id=1, title_english="Solo Leveling", start_year=2018),
                  row(id=2, title_english="Solo Levelling", start_year=2021)]

    assert build_plan(same_year)[0] == {2: 1}
    assert build_plan(other_year)[0] == {}


def test_similarity_ratio_rejects_length_mismatch_before_comparing():
    assert similarity_ratio("Solo Leveling", "Solo Leveling") == pytest.approx(1.0)
    # >10% length difference is treated as "different work", not a typo.
    assert similarity_ratio("Solo Leveling", "Solo Leveling Extra Volume Two") == 0.0
    assert similarity_ratio("", "Solo Leveling") == 0.0


def test_clean_title_lowercases_and_strips():
    assert clean_title("  Blue   Period ") == "blue   period"
    assert clean_title(None) == ""


# ---------------------------------------------------------------------------
# _merge_duplicate_into: the fold keeps data instead of deleting it
# ---------------------------------------------------------------------------


def make_manga(**kwargs) -> Manga:
    """An unpersisted ORM row; the fold helpers only touch attributes."""
    base = dict(
        title_romaji="Survivor",
        genres=[],
        alternative_titles=[],
        tags=[],
        inferred_tags=[],
        similar_mangas=[],
        is_nsfw=False,
    )
    base.update(kwargs)
    return Manga(**base)


def test_fold_unions_categorical_fields_without_duplicates():
    keep = make_manga(genres=["Romance"], tags=[{"name": "Drama"}],
                      inferred_tags=[{"slug": "romance"}],
                      alternative_titles=["Survivor"])
    drop = make_manga(genres=["Romance", "Fantasy"], tags=[{"name": "Drama"}, {"name": "Isekai"}],
                      inferred_tags=[{"slug": "romance"}, {"slug": "isekai"}],
                      alternative_titles=["survivor", "Dropped"])

    _merge_duplicate_into(keep, drop)

    assert keep.genres == ["Romance", "Fantasy"]
    assert [t["name"] for t in keep.tags] == ["Drama", "Isekai"]
    assert [t["slug"] for t in keep.inferred_tags] == ["romance", "isekai"]
    # Case-insensitive dedupe keeps the survivor's spelling.
    assert keep.alternative_titles == ["Survivor", "Dropped"]


def test_fold_fills_empty_columns_and_never_overwrites_a_value():
    keep = make_manga(synopsis=None, average_score=6.0, chapters=10)
    drop = make_manga(synopsis="From the duplicate", average_score=8.5, chapters=4,
                      title_romaji="Dropped")

    _merge_duplicate_into(keep, drop)

    assert keep.synopsis == "From the duplicate"
    assert keep.average_score == 8.5   # better score wins
    assert keep.chapters == 10         # largest count wins
    assert keep.title_romaji == "Survivor"  # a present value is never replaced


def test_fold_does_not_copy_unique_ids_before_the_delete():
    keep = make_manga(mal_id=42, anilist_id=None)
    drop = make_manga(mal_id=None, anilist_id=900)

    _merge_duplicate_into(keep, drop)

    # Copying now would collide with the row that still owns the value.
    assert keep.anilist_id is None
    _fill_external_id_columns(keep, drop)
    assert keep.anilist_id == 900


def test_fold_inherits_nsfw_from_genre_evidence_on_the_duplicate():
    keep = make_manga(genres=["Action"], tags=[], is_nsfw=False)
    drop = make_manga(genres=["Hentai"], is_nsfw=False)

    _merge_duplicate_into(keep, drop)

    assert keep.is_nsfw is True


def test_similar_edges_union_and_drop_the_self_edge():
    keep = make_manga(id=1, similar_mangas=[{"id": 5, "score": 0.5}])
    drop = make_manga(id=2, similar_mangas=[
        {"id": 1, "score": 0.99},   # points back at the survivor: self edge
        {"id": 5, "score": 0.8},    # same target, better score
        {"id": 6, "score": 0.4},
        {"id": 7, "score": 0.3},    # already resolved to 6 by the plan
    ])

    total = _merge_similar_edges(keep, drop, resolve=lambda target: 6 if target == 7 else target)

    # Two distinct targets survive the fold; the self edge is dropped.
    assert total == 2
    assert keep.similar_mangas == [
        {"id": 5, "score": 0.8},
        {"id": 6, "score": 0.4},
    ]


def test_similar_edges_are_noop_when_the_duplicate_has_none():
    keep = make_manga(id=1, similar_mangas=[{"id": 5, "score": 0.5}])
    drop = make_manga(id=2, similar_mangas=None)

    assert _merge_similar_edges(keep, drop, resolve=lambda t: t) == 0
    assert keep.similar_mangas == [{"id": 5, "score": 0.5}]


@pytest.mark.asyncio
async def test_dry_run_merge_on_an_empty_catalogue_reports_nothing_to_do():
    from app.ingestion.merge import run_merge_pass

    summary = await run_merge_pass(dry_run=True)

    assert summary["dry_run"] is True
    assert summary["pairs"] == 0
    assert summary["rows_deleted"] == 0
