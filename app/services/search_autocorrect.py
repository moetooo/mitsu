import re
from typing import Iterable, List, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db_models import Manga

WORD_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*", re.IGNORECASE)
MIN_TOKEN_LENGTH = 4
MAX_VOCABULARY_SIZE = 100_000

_vocabulary: Set[str] | None = None


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


def _words(values: Iterable[str | None]) -> Set[str]:
    vocabulary: Set[str] = set()
    for value in values:
        if value:
            vocabulary.update(
                word for word in WORD_RE.findall(value.lower())
                if len(word) >= MIN_TOKEN_LENGTH
            )
    return vocabulary


async def _get_vocabulary(db: AsyncSession) -> Set[str]:
    global _vocabulary
    if _vocabulary is not None:
        return _vocabulary

    result = await db.execute(select(Manga.title_english, Manga.title_romaji, Manga.genres))
    values: List[str | None] = []
    for title_english, title_romaji, genres in result.all():
        values.extend((title_english, title_romaji))
        values.extend(genres or [])
    _vocabulary = set(sorted(_words(values))[:MAX_VOCABULARY_SIZE])
    return _vocabulary


def _correction_for_token(token: str, vocabulary: Set[str]) -> str:
    normalized = token.lower()
    if len(normalized) < MIN_TOKEN_LENGTH or normalized in vocabulary:
        return token

    max_distance = max(1, min(3, len(normalized) // 5))
    candidates = [
        word for word in vocabulary
        if abs(len(word) - len(normalized)) <= max_distance
    ]
    ranked = sorted(
        ((levenshtein_distance(normalized, candidate), candidate) for candidate in candidates),
        key=lambda item: item[0],
    )
    if not ranked or ranked[0][0] > max_distance:
        return token
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return token
    
    replacement = ranked[0][1]
    if token.istitle():
        return replacement.capitalize()
    return replacement


async def autocorrect_query(query: str, db: AsyncSession) -> str:
    vocabulary = await _get_vocabulary(db)
    return WORD_RE.sub(
        lambda match: _correction_for_token(match.group(0), vocabulary),
        query,
    )