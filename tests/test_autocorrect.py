"""SVC-05 and ARCH-14, Stage 7B: autocorrect stops guessing.

Three properties, each a defect that was measured live:

* the vocabulary keeps **frequent** words when the cap bites, not the
  alphabetically early ones (SVC-05);
* a correction is only made when a search finds **nothing**, so a query that
  works is answered exactly as typed. Before this, `romance between rivals` was
  silently searched as `romance between rival` -- captured in
  `checks/svc_7b_parity.py`, the only diff between the two runs;
* the vocabulary is shared and invalidatable (ARCH-14), instead of a module
  global that no sync could refresh.
"""

from __future__ import annotations

import types

import pytest

from tests.conftest import catalog_row

from app.models import RecommendRequest
from app.services import cache
from app.services import search_autocorrect as autocorrect
from app.services.search_autocorrect import (
    _correction_for_token,
    build_vocabulary,
    levenshtein_distance,
)


# ------------------------------------------------------------------ vocabulary
def test_vocabulary_keeps_frequent_words_when_capped():
    """The old vocabulary was `sorted(tokens)[:100_000]`: alphabetical, not useful.

    With a cap of 4 and five candidates, the frequent word must survive and the
    alphabetically early but rare one must be the one dropped.
    """
    values = ["aardvark"] + ["zebra"] * 10 + ["walrus"] * 9 + ["viper"] * 8 + ["cobra"]

    vocabulary = build_vocabulary(values, size=3)
    kept = {word for words in vocabulary.values() for word in words}

    # Alphabetical (the old behaviour) would keep aardvark, cobra, viper;
    # frequency keeps the three common words.
    assert kept == {"zebra", "walrus", "viper"}


def test_vocabulary_buckets_are_keyed_by_length():
    vocabulary = build_vocabulary(["berserk", "naruto"])

    assert set(vocabulary) == {6, 7}
    assert "naruto" in vocabulary[6]


def test_known_token_is_never_changed():
    vocabulary = build_vocabulary(["berserk", "naruto"])

    assert _correction_for_token("berserk", vocabulary) == "berserk"
    assert _correction_for_token("Naruto", vocabulary) == "Naruto"


def test_unknown_token_with_no_close_match_is_left_alone():
    vocabulary = build_vocabulary(["berserk", "naruto"])

    assert _correction_for_token("zqxjv", vocabulary) == "zqxjv"
    assert _correction_for_token("gojo", vocabulary) == "gojo"


def test_typo_is_corrected_and_capitalisation_preserved():
    vocabulary = build_vocabulary(["berserk"])

    assert _correction_for_token("bersrk", vocabulary) == "berserk"
    assert _correction_for_token("Bersrk", vocabulary) == "Berserk"


def test_a_tie_is_not_guessed():
    """`bolt`/`belt` are equally far from `bult`; picking one would be a coin flip."""
    vocabulary = build_vocabulary(["bolt", "belt"])

    assert _correction_for_token("bult", vocabulary) == "bult"


# ------------------------------------------------------- the bucketed fast path
def _full_scan_correction(token: str, vocabulary: set[str]) -> str:
    """The pre-7B algorithm: every candidate, no length or q-gram pruning."""
    normalized = token.lower()
    if len(normalized) < autocorrect.MIN_TOKEN_LENGTH or normalized in vocabulary:
        return token
    max_distance = max(1, min(3, len(normalized) // 5))
    candidates = [w for w in vocabulary if abs(len(w) - len(normalized)) <= max_distance]
    ranked = sorted((levenshtein_distance(normalized, w), w) for w in candidates)
    if not ranked or ranked[0][0] > max_distance:
        return token
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return token
    replacement = ranked[0][1]
    return replacement.capitalize() if token.istitle() else replacement


def test_pruning_does_not_change_any_answer():
    """Length buckets + the bigram filter are an optimisation, not a decision."""
    words = [
        "berserk", "berserker", "naruto", "frieren", "monster", "hunter",
        "rival", "rivals", "rivalry", "lookism", "bookish", "pice",
    ]
    vocabulary = build_vocabulary(words)

    for token in ["bersrk", "bersrker", "rivals", "lookism", "pice", "monstr", "narutoo"]:
        assert _correction_for_token(token, vocabulary) == _full_scan_correction(token, set(words)), token


def test_plain_set_input_still_works():
    """The unit tests and any caller may pass a plain set of words."""
    words = {"berserk", "naruto"}

    assert _correction_for_token("bersrk", words) == "berserk"


# ------------------------------------------------------------- invalidation
def test_vocabulary_key_is_invalidated_with_the_catalog_caches():
    """ARCH-14: the vocabulary is derived data, so a catalog write must drop it."""
    assert any(
        pattern.startswith("catalog:vocab")
        for pattern in cache._CATALOG_CACHE_PATTERNS
    )


@pytest.mark.asyncio
async def test_invalidation_actually_deletes_the_vocabulary():
    await cache.set_cached(autocorrect.VOCABULARY_CACHE_KEY, {"6": "berserk"}, ttl=60)
    assert await cache.get_cached(autocorrect.VOCABULARY_CACHE_KEY) == {"6": "berserk"}

    await cache.invalidate_catalog_caches()

    assert await cache.get_cached(autocorrect.VOCABULARY_CACHE_KEY) is None


# ------------------------------------------------- correction only when empty
@pytest.fixture
def no_cache(monkeypatch):
    """Every handler in this file must exercise code, not a Redis answer."""

    async def _miss(*_args, **_kwargs):
        return None

    for module_name in ("app.routers.search", "app.routers.recommend"):
        module = __import__(module_name, fromlist=["get_cached"])
        monkeypatch.setattr(module, "get_cached", _miss)
        monkeypatch.setattr(module, "set_cached", _miss)


@pytest.mark.asyncio
async def test_search_does_not_correct_when_the_query_matches(monkeypatch, no_cache):
    """A search that finds something is answered as typed, with no correction."""
    from app.routers import search as search_router

    async def fail(*_args, **_kwargs):
        raise AssertionError("autocorrect must not run when the search found rows")

    async def finds_rows(*_args, **_kwargs):
        return [catalog_row("Berserk", seed=7, id=1)]

    monkeypatch.setattr(search_router, "autocorrect_query", fail)
    monkeypatch.setattr(search_router.catalog, "search_titles", finds_rows)

    response = await search_router.search_manga(q="berserk", response=types.SimpleNamespace(headers={}), db=None)

    assert [row["title_english"] for row in response] == ["Berserk"]


@pytest.mark.asyncio
async def test_search_corrects_only_after_an_empty_result(monkeypatch, no_cache):
    """`bersrk` -> nothing -> corrected -> results, and the typed term is tried first."""
    from app.routers import search as search_router

    terms: list[str] = []

    async def search_titles(_db, term, *, limit=10, offset=0):
        terms.append(term)
        if term == "berserk":
            return [catalog_row("Berserk", seed=7, id=1)]
        return []

    async def correct(query, _db):
        return "berserk" if query == "bersrk" else query

    monkeypatch.setattr(search_router, "autocorrect_query", correct)
    monkeypatch.setattr(search_router.catalog, "search_titles", search_titles)

    response = await search_router.search_manga(q="bersrk", response=types.SimpleNamespace(headers={}), db=None)

    assert terms == ["bersrk", "berserk"]
    assert [row["title_english"] for row in response] == ["Berserk"]


@pytest.mark.asyncio
async def test_search_reports_the_uncorrected_query_when_the_correction_also_fails(
    monkeypatch, no_cache
):
    """No confident correction, or a correction that also finds nothing: empty list."""
    from app.routers import search as search_router

    async def search_titles(*_args, **_kwargs):
        return []

    async def same(query, _db):
        return query

    monkeypatch.setattr(search_router, "autocorrect_query", same)
    monkeypatch.setattr(search_router.catalog, "search_titles", search_titles)

    assert await search_router.search_manga(
        q="jjjjjjjj", response=types.SimpleNamespace(headers={}), db=None
    ) == []


@pytest.mark.asyncio
async def test_recommend_answers_as_typed_and_does_not_retry(monkeypatch):
    """A query that works must not be corrected -- the live case was `rivals`."""
    from app.routers import recommend as recommend_router

    asked: list[str] = []

    async def answer(_db, request):
        asked.append(request.query)
        rows = [{"manga": object()}]
        return recommend_router._Answer(rows, request.query, None, 0.0, 0.0, False)

    async def correct(_query, _db):
        raise AssertionError("autocorrect must not run when the answer is non-empty")

    monkeypatch.setattr(recommend_router, "_answer_query", answer)
    monkeypatch.setattr(recommend_router, "autocorrect_query", correct)

    request = RecommendRequest(query="romance between rivals")
    result = await recommend_router._answer_with_fallback(db=None, request=request)

    assert asked == ["romance between rivals"]
    assert result.corrected_query == "romance between rivals"
    assert request.query == "romance between rivals"


@pytest.mark.asyncio
async def test_recommend_retries_once_with_the_corrected_query(monkeypatch):
    """Empty answer -> one correction -> one retry, and the typed query is restored."""
    from app.routers import recommend as recommend_router

    asked: list[str] = []
    answers = {"bersrk": [], "berserk": [{"manga": object()}]}

    async def answer(_db, request):
        asked.append(request.query)
        return recommend_router._Answer(
            answers.get(request.query, []), request.query, None, 0.0, 0.0, False
        )

    async def correct(query, _db):
        return "berserk" if query == "bersrk" else query

    monkeypatch.setattr(recommend_router, "_answer_query", answer)
    monkeypatch.setattr(recommend_router, "autocorrect_query", correct)

    request = RecommendRequest(query="bersrk")
    result = await recommend_router._answer_with_fallback(db=None, request=request)

    assert asked == ["bersrk", "berserk"]
    assert result.corrected_query == "berserk"
    assert result.top_candidates


@pytest.mark.asyncio
async def test_recommend_keeps_the_empty_answer_when_the_retry_is_empty_too(monkeypatch):
    from app.routers import recommend as recommend_router

    async def answer(_db, request):
        return recommend_router._Answer([], request.query, None, 0.0, 0.0, False)

    async def correct(_query, _db):
        return "something else"

    monkeypatch.setattr(recommend_router, "_answer_query", answer)
    monkeypatch.setattr(recommend_router, "autocorrect_query", correct)

    request = RecommendRequest(query="jjjjjjjj")
    result = await recommend_router._answer_with_fallback(db=None, request=request)

    assert result.top_candidates == []
    assert result.corrected_query == "jjjjjjjj"
    assert request.query == "jjjjjjjj"
