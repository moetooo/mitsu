"""Spelling correction for the title jump box and the recommend box (SVC-05, ARCH-14).

The old implementation had four defects, and three of them came from the same
place -- it guessed up front, on every request, from a process-global snapshot:

* **Alphabetical truncation.** The vocabulary was `sorted(vocabulary)[:100_000]`.
  At today's 95,626 rows that cap is not reached (73,515 tokens), so the damage
  was latent rather than live; the moment the catalogue grows past the cap, every
  correction for a word sorting after the cutoff stops firing. Tokens are now kept
  by **frequency**, which is what a spelling model should keep.
* **A 567 ms scan on the event loop.** For each unknown token the code walked the
  whole vocabulary computing edit distances -- measured at 567-582 ms for one
  typo, on every uncached request. The vocabulary is now bucketed by word length,
  a bigram test prunes candidates that cannot be one edit away, and the whole
  thing runs only when a search found nothing: 83 ms for that typo, and 0 ms on
  every request that does match.
* **Silent rewriting of valid words.** A word the catalogue does not contain (a
  character name, a romaji term) was replaced by the nearest title word, with no
  indication. That is now the *caller's* decision: both endpoints correct only
  after a search returned **nothing**, so a query that works is never rewritten.
* **Never invalidated.** `_vocabulary` was a module global, filled once per
  process; a sync could not refresh it and every worker held a different snapshot
  (ARCH-14). It now lives in Redis under `catalog:vocab:v1`, which
  `cache.invalidate_catalog_caches()` deletes along with the other catalog-derived
  keys, with a TTL as the backstop.

What is deliberately kept: Levenshtein with a unique-best rule. A trigram
correction was measured as a replacement and is *worse* for typos -- `%>` over the
title columns answers `bersrk` with nothing at all and `lookism` with
"Looking for the one" -- so the substring index stays a search index, not a
spelling model.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db_models import Manga
from .cache import get_cached, set_cached

WORD_RE = re.compile(r"[a-z0-9]+(?:['\-][a-z0-9]+)*", re.IGNORECASE)
MIN_TOKEN_LENGTH = 4
MAX_VOCABULARY_SIZE = 100_000

#: Shared by every worker, and deleted by `cache.invalidate_catalog_caches()`.
VOCABULARY_CACHE_KEY = "catalog:vocab:v1"
VOCABULARY_TTL_SECONDS = 3600

#: The vocabulary travels from Redis as one newline-joined string per word length.
NEWLINE = chr(10)

Vocabulary = Dict[int, Set[str]]


def levenshtein_distance(left: str, right: str) -> int:
    """Return the minimum single-character edit count between two strings."""
    if len(left) < len(right):
        left, right = right, left
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def _tokens(values: Iterable[str | None]) -> Iterable[str]:
    for value in values:
        if value:
            for word in WORD_RE.findall(value.lower()):
                if len(word) >= MIN_TOKEN_LENGTH:
                    yield word


def _words(values: Iterable[str | None]) -> Set[str]:
    """The distinct long-enough tokens in `values` (kept for the unit tests)."""
    return set(_tokens(values))


def build_vocabulary(values: Iterable[str | None], *, size: int = MAX_VOCABULARY_SIZE) -> Vocabulary:
    """Frequency-ordered vocabulary, bucketed by word length.

    `size` caps the token count; ties are broken alphabetically so the result is
    deterministic. Before the cap is reached the ordering does not matter -- it
    matters precisely when it bites, and then it must not be alphabetical.
    """
    counts = Counter(_tokens(values))
    buckets: Vocabulary = {}
    for word, _ in counts.most_common(size):
        buckets.setdefault(len(word), set()).add(word)
    return buckets


def _bucketise(vocabulary: Set[str]) -> Vocabulary:
    buckets: Vocabulary = {}
    for word in vocabulary:
        buckets.setdefault(len(word), set()).add(word)
    return buckets


def _as_buckets(vocabulary: Set[str] | Vocabulary) -> Vocabulary:
    """Accept a plain set as well as buckets, so callers cannot pass the wrong shape."""
    if not vocabulary or isinstance(next(iter(vocabulary)), int):
        return vocabulary  # type: ignore[return-value]
    return _bucketise(vocabulary)  # type: ignore[arg-type]


def _bigrams(word: str) -> Set[str]:
    return {word[index:index + 2] for index in range(len(word) - 1)}


def _correction_for_token(token: str, vocabulary: Set[str] | Vocabulary) -> str:
    """The single best correction for one token, or the token itself.

    Unchanged rules: a token is left alone when it is already known, and a tie
    between two equally distant candidates is treated as no evidence at all.

    Two refinements, both measured. The vocabulary is bucketed by word length, so
    only buckets within the edit distance are opened at all; and a two-character
    q-gram test drops candidates that cannot be within one edit before the
    Levenshtein cost is paid (a single substitution destroys at most three
    bigrams, so a one-edit neighbour always shares at least one). Together they
    took one miss from **527 ms to 71-83 ms** (133 ms for the worst token
    tried) without changing a single answer.
    """
    normalized = token.lower()
    if len(normalized) < MIN_TOKEN_LENGTH:
        return token

    buckets = _as_buckets(vocabulary)
    if normalized in buckets.get(len(normalized), set()):
        return token

    max_distance = max(1, min(3, len(normalized) // 5))
    token_bigrams = _bigrams(normalized)
    ranked: List[tuple[int, str]] = []
    for length in range(len(normalized) - max_distance, len(normalized) + max_distance + 1):
        for candidate in buckets.get(length, ()):  # only nearby lengths are compared
            if not _bigrams(candidate) & token_bigrams:
                continue  # cannot be one edit away
            ranked.append((levenshtein_distance(normalized, candidate), candidate))

    ranked.sort(key=lambda item: item[0])
    if not ranked or ranked[0][0] > max_distance:
        return token
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return token

    replacement = ranked[0][1]
    if token.istitle():
        return replacement.capitalize()
    return replacement


async def _load_vocabulary(db: AsyncSession) -> Vocabulary:
    """The shared vocabulary: Redis first, catalogue second."""
    cached = await get_cached(VOCABULARY_CACHE_KEY)
    if cached:
        # Stored as newline-joined text, not a JSON list: decoding 73,515 words
        # through `json.loads` cost ~400 ms, `str.split` costs a fraction of it.
        return {int(length): set(words.split(NEWLINE)) for length, words in cached.items()}

    result = await db.execute(
        select(Manga.title_english, Manga.title_romaji, Manga.genres, Manga.alternative_titles)
    )
    values: List[str | None] = []
    for title_english, title_romaji, genres, alt_titles in result.all():
        values.extend((title_english, title_romaji))
        values.extend(genres or [])
        values.extend(alt_titles or [])

    vocabulary = build_vocabulary(values)
    await set_cached(
        VOCABULARY_CACHE_KEY,
        {str(length): NEWLINE.join(sorted(words)) for length, words in vocabulary.items()},
        ttl=VOCABULARY_TTL_SECONDS,
    )
    return vocabulary


async def autocorrect_query(query: str, db: AsyncSession) -> str:
    """Correct spellings in `query`, token by token.

    Call this **after** a search has found nothing, not before it: a query that
    works must come back exactly as it was typed.
    """
    if not query:
        return query
    vocabulary = await _load_vocabulary(db)
    return WORD_RE.sub(
        lambda match: _correction_for_token(match.group(0), vocabulary),
        query,
    )
