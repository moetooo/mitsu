"""Publication format is stored once and read from the column (ARCH-05).

Before this, three things existed and none of them was a column:

* `infer_format_type(...)` in Python, used for result payloads;
* a ~120-line SQL predicate that re-derived the same answer per query;
* `RecommendationResult.format_type`, always `None` for database-backed rows.

Two properties are worth guarding:

1. The SQL backfill in revision 0005 must agree with the Python classifier.
   If they drift, a row's stored format depends on when it was written.
2. A format filter must return every row. The old predicate was
   `NOT (title_native ~ ... OR ...)`, which for a row with a NULL
   `title_native` evaluates to NULL — so 5,992 titles (6.3% of the catalog)
   matched *no* format filter at all.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from app.db import AsyncSessionLocal, engine
from app.db_models import Manga
from app.ingestion.normalize import anilist_to_record, mangadex_to_record
from app.ingestion.upsert import smart_upsert_manga_ex
from app.services.format import (
    MANGA,
    MANHUA,
    MANHWA,
    build_format_sql_condition,
    filter_values,
    format_type_for_row,
    infer_format_type,
)

BACKFILL_MODULE = (
    Path(__file__).resolve().parent.parent / "migrations" / "versions" / "0005_format_type.py"
)

PROBES = (
    # (label, title_native, tags, genres, site_url, inferred_tags)
    ("plain japanese", "進撃の巨人", [{"name": "Action"}], ["Action"], "https://anilist.co/manga/1", None),
    ("hangul title", "나 혼자만 레벨업", [], ["Action"], None, None),
    ("webtoon tag", None, [{"name": "Webtoon"}], [], None, None),
    ("no native, no tags", None, [], [], None, None),
    ("manhua tags", None, [{"name": "Manhua"}], [], None, None),
    ("hanzi strip", "一条狗", [{"name": "Long Strip"}], [], None, None),
    ("hanzi with kana", "ブリーチ中文", [{"name": "Full Color"}], [], None, None),
    ("inferred manhwa wins", None, [{"name": "Manhua"}], [], None, [{"slug": "manhwa"}]),
    ("inferred manga wins", "나 혼자", [{"name": "Webtoon"}], [], None, [{"slug": "manga"}]),
)


def _backfill_sql() -> str:
    source = BACKFILL_MODULE.read_text(encoding="utf-8")
    start = source.index('BACKFILL_SQL = f"""')
    end = source.index('"""', start + len('BACKFILL_SQL = f"""'))
    # Evaluate the f-string so the character ranges are real characters.
    namespace: dict[str, str] = {}
    for name in ("HANGUL_RANGE", "KANA_RANGE", "HANZI_RANGE"):
        marker = source.index(f"{name} = ")
        line = source[marker:].splitlines()[0]
        namespace[name] = eval(line.split("=", 1)[1].strip())  # noqa: S307 - test only
    return eval('f"""' + source[start + len('BACKFILL_SQL = f"""') : end] + '"""', namespace)  # noqa: S307


# --- the classifier -------------------------------------------------------


def test_inferred_tag_beats_every_other_signal():
    assert infer_format_type(title_native="나 혼자", inferred_tags=[{"slug": "manga"}]) == MANGA
    assert infer_format_type(tags=[{"name": "Manhua"}], inferred_tags=[{"slug": "manhwa"}]) == MANHWA


def test_unknown_filter_values_are_ignored():
    assert filter_values(["manhwa", "manhwa", None, 42, "bogus"]) == [MANHWA]
    assert filter_values(None) == []
    assert build_format_sql_condition(["bogus"]) is None


def test_ingestion_classifies_on_write():
    """Both sources store a format, so no reader has to guess."""
    anilist = anilist_to_record({
        "id": 1,
        "title": {"romaji": "Solo Leveling", "native": "나 혼자만 레벨업"},
        "genres": ["Action"],
        "tags": [],
    })
    assert anilist["format_type"] == MANHWA

    mangadex = mangadex_to_record({
        "id": "abc",
        "attributes": {
            "originalLanguage": "zh",
            "title": {"en": "X"},
            "tags": [],
            "contentRating": "safe",
        },
    })
    assert mangadex["format_type"] == MANHUA


# --- the migration mirrors the classifier ---------------------------------


@pytest.mark.asyncio
async def test_backfill_sql_agrees_with_the_classifier():
    """Revision 0005's CASE must classify exactly what the Python rule does."""
    sql = _backfill_sql()
    async with engine.begin() as conn:
        ids = []
        for label, native, tags, genres, site_url, inferred in PROBES:
            manga_id = await conn.scalar(
                sa.text(
                    """
                    INSERT INTO manga (title_romaji, title_native, tags, genres, site_url, inferred_tags, format_type)
                    VALUES (:label, :native, CAST(:tags AS jsonb), CAST(:genres AS text[]), :site_url,
                            CAST(:inferred AS jsonb), NULL)
                    RETURNING id
                    """
                ),
                {
                    "label": f"format probe {label}",
                    "native": native,
                    "tags": _json(tags),
                    "genres": genres,
                    "site_url": site_url,
                    "inferred": _json(inferred),
                },
            )
            ids.append(manga_id)

        await conn.execute(sa.text("SET statement_timeout = '60s'"))
        await conn.execute(sa.text(sql))
        await conn.execute(sa.text("SET statement_timeout TO DEFAULT"))

        rows = (await conn.execute(
            sa.text("SELECT format_type FROM manga WHERE id = ANY(:ids)"),
            {"ids": ids},
        )).scalars().all()

        await conn.execute(sa.text("DELETE FROM manga WHERE id = ANY(:ids)"), {"ids": ids})

    expected = [infer_format_type(n, t, g, s, i) for _, n, t, g, s, i in PROBES]
    assert list(rows) == expected


@pytest.mark.asyncio
async def test_backfill_is_idempotent():
    """It only touches rows that have no value yet."""
    sql = _backfill_sql()
    async with engine.begin() as conn:
        manga_id = await conn.scalar(sa.text(
            "INSERT INTO manga (title_romaji, title_native, format_type) "
            "VALUES ('format probe idempotent', '나 혼자', 'MANGA') RETURNING id"
        ))
        await conn.execute(sa.text(sql))
        stored = await conn.scalar(
            sa.text("SELECT format_type FROM manga WHERE id = :id"), {"id": manga_id}
        )
        await conn.execute(sa.text("DELETE FROM manga WHERE id = :id"), {"id": manga_id})

    assert stored == "MANGA", "an already-classified row must not be rewritten"


# --- writes keep the column honest ---------------------------------------


@pytest.mark.asyncio
async def test_upsert_recomputes_format_when_new_evidence_arrives():
    """A second source adding a Webtoon tag must change the stored format."""
    async with AsyncSessionLocal() as session:
        first = await smart_upsert_manga_ex(session, {
            "anilist_id": 9_999_8201,
            "title_romaji": "Format Merge Probe",
            "title_native": "進撃の巨人",
            "genres": ["Action"],
            "tags": [{"name": "Action"}],
        })
        assert first.manga.format_type == MANGA

        second = await smart_upsert_manga_ex(session, {
            "anilist_id": 9_999_8201,
            "title_romaji": "Format Merge Probe",
            "genres": ["Action"],
            "tags": [{"name": "Webtoon"}, {"name": "Action"}],
        })
        assert second.action == "updated", "the second write must merge, not insert again"
        await session.commit()

    async with AsyncSessionLocal() as session:
        stored = await session.scalar(
            sa.text("SELECT format_type FROM manga WHERE anilist_id = :id"), {"id": 9_999_8201}
        )
        await session.execute(
            sa.text("DELETE FROM manga WHERE anilist_id = :id"), {"id": 9_999_8201}
        )
        await session.commit()

    assert stored == MANHWA, "the added Webtoon tag must be reflected in the stored format"


@pytest.mark.asyncio
async def test_row_helper_matches_the_record_helper():
    row = Manga(title_native="나 혼자", tags=[], genres=[], site_url=None, inferred_tags=None)
    assert format_type_for_row(row) == MANHWA


def _json(value) -> str | None:
    import json

    return None if value is None else json.dumps(value)
