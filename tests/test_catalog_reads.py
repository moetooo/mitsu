"""Unit tests for the catalogue reads and the featured rail (ARCH-07).

Everything here is pure: these are the parts of the two new service modules
that decide something (escaping, quotas, ordering, the payload contract) and
therefore can be tested without a database. The SQL those functions issue is
covered by the endpoint tests that already existed
(`test_contract_validation.py`, `test_safety_and_pagination.py`,
`test_api_endpoints.py`) and by the parity probe run before the refactor.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db_models import Manga
from app.services import catalog, featured


# --------------------------------------------------------------------------
# LIKE escaping - API-08's "the escape is real" half
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("berserk", "berserk"),
        ("50%", "50\\%"),
        ("a_b", "a\\_b"),
        ("back\\slash", "back\\\\slash"),
        ("%_\\", "\\%\\_\\\\"),
    ],
)
def test_escape_like_neutralises_metacharacters(raw, escaped):
    assert catalog.escape_like(raw) == escaped


def test_like_pattern_wraps_and_escapes_in_one_step():
    """Callers pass the raw term, so the escape cannot be forgotten."""
    assert catalog.like_pattern("50%") == "%50\\%%"


# --------------------------------------------------------------------------
# The featured rail: quotas, dedupe, fill, determinism
# --------------------------------------------------------------------------


def _rows(prefix: str, count: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=f"{prefix}{index}") for index in range(count)]


def _pools(**sizes: int) -> dict[str, list[SimpleNamespace]]:
    return {name: _rows(name, size) for name, size in sizes.items()}


def test_featured_quota_is_two_per_pool():
    pools = _pools(popular=10, underrated=10, acclaimed=10, fallback=10)
    picked = featured.select_items(pools, limit=6, rng=random.Random("slot"))

    badges = [badge for _manga, badge in picked]
    assert sorted(badges) == sorted(
        ["Popular Pick", "Popular Pick", "Hidden Gem", "Hidden Gem",
         "Critically Acclaimed", "Critically Acclaimed"]
    )
    assert len(picked) == 6


def test_featured_never_repeats_a_title_across_pools():
    """The same row can be popular *and* acclaimed; it may only appear once."""
    shared = _rows("shared", 3)
    pools = {
        "popular": shared,
        "underrated": shared,
        "acclaimed": shared,
        "fallback": _rows("fallback", 10),
    }
    picked = featured.select_items(pools, limit=6, rng=random.Random("slot"))

    ids = [manga.id for manga, _badge in picked]
    assert len(ids) == len(set(ids)) == 6, "a shared row may only appear once"
    shared_ids = [manga_id for manga_id in ids if str(manga_id).startswith("shared")]
    assert sorted(shared_ids) == ["shared0", "shared1", "shared2"], (
        "the three shared rows must fill three slots, not nine"
    )


def test_featured_fills_the_rail_from_the_fallback():
    pools = _pools(popular=2, underrated=2, acclaimed=2, fallback=10)
    picked = featured.select_items(pools, limit=8, rng=random.Random("slot"))

    assert len(picked) == 8
    assert [badge for _manga, badge in picked].count(featured.FALLBACK_BADGE) == 2


def test_featured_is_reproducible_within_a_slot_and_moves_between_slots():
    """Same seed, same rail; different seed, (almost certainly) a different rail."""
    pools = _pools(popular=20, underrated=20, acclaimed=20, fallback=40)

    first = [manga.id for manga, _ in featured.select_items(pools, 6, random.Random("a"))]
    again = [manga.id for manga, _ in featured.select_items(pools, 6, random.Random("a"))]
    other = [manga.id for manga, _ in featured.select_items(pools, 6, random.Random("b"))]

    assert first == again
    assert first != other


def test_featured_survives_an_empty_catalogue():
    """A fresh database must answer an empty rail, not raise."""
    picked = featured.select_items({"fallback": []}, limit=6, rng=random.Random("slot"))
    assert picked == []


def test_slot_key_is_stable_inside_a_quarter_hour():
    start = datetime(2026, 11, 14, 19, 15, 0, tzinfo=timezone.utc)
    same_slot = start + timedelta(minutes=14, seconds=59)
    next_slot = start + timedelta(minutes=15)

    assert featured.slot_key(start) == featured.slot_key(same_slot) == "2026-11-14-19-15"
    assert featured.slot_key(next_slot) == "2026-11-14-19-30"


def test_featured_cache_key_separates_slots_and_limits():
    assert featured.cache_key("2026-11-14-19-15", 6) == "manga:featured_mix:2026-11-14-19-15:6"
    assert featured.cache_key("2026-11-14-19-15", 6) != featured.cache_key("2026-11-14-19-30", 6)
    assert featured.cache_key("2026-11-14-19-15", 6) != featured.cache_key("2026-11-14-19-15", 12)


# --------------------------------------------------------------------------
# Payload contract - API-12: no fabricated similarity on a curated row
# --------------------------------------------------------------------------


def test_featured_payload_reports_no_similarity():
    manga = Manga(
        id=7,
        title_english="Probe",
        cover_image_url="https://example.invalid/7.jpg",
        is_nsfw=False,
    )
    payload = featured.payload_for(manga, "Popular Pick")

    assert payload["id"] == 7
    assert payload["similarity_score"] is None
    assert payload["llm_reasoning"] is None
    assert payload["category_badge"] == "Popular Pick"
