"""The write seam: one function decides what the cover columns contain.

Why this file exists: the MangaDex outage was not one bug, it was three write paths
that each decided independently what a "cover" was - ingestion on insert, the merge
path on update, and a repair script. `cover_fields()` replaced them, and the tests
here are the two halves of the promise:

* **behaviour** - hostile input through the seam cannot produce a row that claims to
  have a cover it cannot serve;
* **structure** - no module can write the cover block by hand without going through
  the seam, so the second path cannot quietly reappear.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.core import covers as cover_rules

APP_ROOT = Path(__file__).resolve().parent.parent
COVER_COLUMNS = ("cover_image_url", "cover_candidates", "cover_status", "cover_source")

ANILIST = "https://s4.anilist.co/file/anilistcdn/media/manga/cover/large/bx1.jpg"
MAL = "https://cdn.myanimelist.net/images/manga/3/216464.jpg"
MEDX = "https://uploads.mangadex.org/covers/abc/def.png"
INSECURE = "http://cdn.myanimelist.net/images/manga/3/216464.jpg"


# --- behaviour ---------------------------------------------------------------


def test_the_primary_url_is_always_the_first_candidate():
    fields = cover_rules.cover_fields(None, [{"url": MAL}, {"url": ANILIST}])

    assert fields["cover_image_url"] == fields["cover_candidates"][0]["url"]


def test_a_blocked_host_cannot_become_the_primary():
    fields = cover_rules.cover_fields(MEDX, [MEDX])

    assert fields["cover_image_url"] is None
    assert fields["cover_candidates"] == []
    assert fields["cover_status"] == "dead"


def test_a_plain_http_url_is_dead_not_unverified():
    # Mixed content is blocked by the browser no matter how healthy the host is.
    fields = cover_rules.cover_fields(INSECURE)

    assert fields["cover_image_url"] is None
    assert fields["cover_status"] == "dead"


def test_an_unknown_host_is_unverified_rather_than_trusted():
    fields = cover_rules.cover_fields("https://images.example.com/a.jpg")

    assert fields["cover_status"] == "unverified"
    assert fields["cover_source"] == "none", "an unknown host has no provider name we can store"


def test_an_empty_row_is_unverified_and_carries_no_candidate():
    fields = cover_rules.cover_fields(None, [])

    assert fields["cover_image_url"] is None
    assert fields["cover_candidates"] == []
    assert fields["cover_status"] == "unverified"
    assert fields["cover_source"] == "none"


def test_a_good_candidate_wins_over_a_blocked_primary():
    fields = cover_rules.cover_fields(MEDX, [{"url": MEDX}, {"url": ANILIST}])

    assert fields["cover_image_url"] == ANILIST
    assert fields["cover_status"] == "ok"
    assert [c["source"] for c in fields["cover_candidates"]] == ["anilist"]


def test_the_seam_is_idempotent():
    # A repair run that re-processes an unchanged row must produce the same block,
    # or every nightly run churns `updated_at` on the whole catalogue.
    once = cover_rules.cover_fields(None, [{"url": MAL}, {"url": ANILIST}])
    twice = cover_rules.cover_fields(once["cover_image_url"], once["cover_candidates"])

    assert twice == once


def test_the_returned_keys_are_exactly_the_cover_columns():
    fields = cover_rules.cover_fields(ANILIST)
    assert tuple(fields) == cover_rules.COVER_COLUMNS


def test_apply_cover_fields_sets_every_column_on_the_target():
    class Row:
        cover_image_url = None
        cover_candidates = None
        cover_status = None
        cover_source = None

    row = Row()
    cover_rules.apply_cover_fields(row, ANILIST)

    assert row.cover_image_url == ANILIST
    assert row.cover_status == "ok"
    assert row.cover_source == "anilist"
    assert row.cover_candidates[0]["url"] == ANILIST


# --- structure ---------------------------------------------------------------

#: Files that own the rules themselves, or hold the columns as table metadata.
SEAM_OWNERS = {"app/core/covers.py", "app/db_models.py"}

#: What a hand-written write looks like: `x.cover_image_url = ...`, or a keyword in a
#: SQL statement (`.values(cover_status=...)`).
ASSIGNMENT = re.compile(r"\.\s*(cover_image_url|cover_candidates|cover_status|cover_source)\s*=")
#: A SQL statement naming the *URL* columns is a cover decision. `cover_status` on its
#: own is a verdict ("this URL failed twice"), which the verifier owns and which does
#: not choose a cover.
VALUES_KEYWORD = re.compile(r"(cover_image_url|cover_candidates)\s*=")
SEAM_IMPORT = re.compile(r"\b(cover_fields|apply_cover_fields)\b")


def _python_files():
    for root in (APP_ROOT / "app", APP_ROOT / "scripts"):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path, path.relative_to(APP_ROOT).as_posix()


def test_nothing_outside_the_seam_writes_the_whole_cover_block():
    """A module that writes two or more cover columns must import the seam.

    One-column copies still exist (`retrieval._hydrate_candidates` hydrates a
    transient object for serialisation, the verifier flips `cover_status` on its own
    verdict). Two or more is a row's cover being decided, and that decision now has
    exactly one implementation.
    """
    offenders = []
    for path, name in _python_files():
        if name in SEAM_OWNERS:
            continue
        source = path.read_text(encoding="utf-8")
        written = {
            match.group(1) for line in source.splitlines() for match in ASSIGNMENT.finditer(line)
        }
        if len(written) >= 2 and not SEAM_IMPORT.search(source):
            offenders.append(f"{name} writes {sorted(written)}")

    assert not offenders, (
        "cover columns must be produced by app/core/covers.cover_fields: " + "; ".join(offenders)
    )


def test_no_sql_statement_names_a_cover_column_outside_the_seam():
    """`update(Manga).values(cover_image_url=...)` is the shape this rules out.

    The repair script writes `**plan["fields"]`, which is the seam's dict - a
    statement that names the URL column instead is making its own decision. A
    `values(cover_status="dead")` is allowed: that is the verifier recording a
    verdict about an existing URL, not choosing one.
    """
    offenders = []
    for path, name in _python_files():
        if name in SEAM_OWNERS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ".values(" in line and VALUES_KEYWORD.search(line):
                offenders.append(f"{name}:{number}")

    assert not offenders, (
        "write the seam's dict instead of naming cover columns in SQL: " + ", ".join(offenders)
    )


@pytest.mark.parametrize(
    "module",
    ["app/ingestion/upsert.py", "app/ingestion/deduplicate.py", "scripts/resolve_covers.py"],
)
def test_every_cover_write_path_imports_the_seam(module):
    source = (APP_ROOT / module).read_text(encoding="utf-8")
    assert SEAM_IMPORT.search(source), f"{module} must build cover columns with cover_fields"


def test_the_seam_module_imports_nothing_from_a_layer_above_it():
    # `app.core` is a leaf (tests/test_layering.py); re-checked here because the seam
    # is now imported by ingestion, services, scripts and the response models.
    tree = ast.parse((APP_ROOT / "app/core/covers.py").read_text(encoding="utf-8"))
    imported = {
        (node.level, node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level
    }
    # `from ..config import settings` - configuration is the only thing below it that
    # `app.core` is allowed to use (tests/test_layering.py).
    assert imported <= {(2, "config")}, f"unexpected import in the seam: {sorted(imported)}"

# --- the seam end-to-end through ingestion -----------------------------------

#: Ids far outside anything real, so these rows cannot collide with the catalogue.
SEAM_ID = 900000111


async def _cleanup():
    from sqlalchemy import text

    from app.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM manga_external_ids WHERE manga_id IN (SELECT id FROM manga WHERE anilist_id = :a)"),
            {"a": SEAM_ID},
        )
        await session.execute(text("DELETE FROM manga WHERE anilist_id = :a"), {"a": SEAM_ID})
        await session.commit()


@pytest.fixture
async def clean_seam_row():
    await _cleanup()
    yield
    await _cleanup()


async def test_ingesting_a_blocked_cover_url_writes_a_dead_row(clean_seam_row):
    """The original bug: ingestion stored MangaDex URLs as if they were covers."""
    from app.db import AsyncSessionLocal
    from app.ingestion.upsert import smart_upsert_manga

    async with AsyncSessionLocal() as session:
        row = await smart_upsert_manga(
            session,
            {
                "anilist_id": SEAM_ID,
                "title_romaji": "Seam Fixture",
                "cover_image_url": MEDX,
            },
        )

        assert row.cover_image_url is None, "a blocked host must never be stored as the cover"
        assert row.cover_candidates == []
        assert row.cover_status == "dead"
        assert row.cover_source == "mangadex", "the source is still recorded, for diagnosis"

        await session.rollback()


async def test_a_blocked_incoming_cover_cannot_demote_a_healthy_row(clean_seam_row):
    """A later MangaDex sync must not overwrite a working AniList cover."""
    from app.db import AsyncSessionLocal
    from app.ingestion.upsert import smart_upsert_manga

    async with AsyncSessionLocal() as session:
        await smart_upsert_manga(
            session,
            {"anilist_id": SEAM_ID, "title_romaji": "Seam Fixture", "cover_image_url": ANILIST},
        )
        row = await smart_upsert_manga(
            session,
            {"anilist_id": SEAM_ID, "title_romaji": "Seam Fixture", "cover_image_url": MEDX},
        )

        assert row.cover_image_url == ANILIST
        assert row.cover_status == "ok"
        assert MEDX not in [c["url"] for c in row.cover_candidates]

        await session.rollback()
