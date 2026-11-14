"""The single owner of the NSFW visibility decision.

Before this module existed the check lived in `retrieval.py` only, so every new
query path (`/search`, featured, trending) was a new leak. Everything that can
return a title to a public caller now asks this module, and the decision is
backed by the persisted `manga.is_nsfw` column instead of a genre blacklist.

`is_nsfw` is decided once, at ingestion time, from provider metadata:

* MangaDex ``contentRating`` -> ``erotica`` / ``pornographic``
* AniList ``isAdult`` -> true
* genre/tag evidence (the old heuristic) is kept only as a fallback for rows
  that predate the column or arrive without a rating.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

NSFW_GENRES = ("Hentai", "Erotica")
NSFW_TAGS = ("Hentai", "Erotica", "Explicit", "Pornographic", "NSFW")
_MANGADEX_ADULT_RATINGS = ("erotica", "pornographic")


def _names(values: Optional[Iterable[Any]]) -> set[str]:
    names: set[str] = set()
    for value in values or ():
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str):
                names.add(name.strip().lower())
        elif isinstance(value, str):
            names.add(value.strip().lower())
    return names


def genre_evidence_is_nsfw(genres: Optional[Iterable[Any]], tags: Optional[Iterable[Any]] = None) -> bool:
    """Fallback heuristic: explicit genre or tag evidence."""
    genres_lower = _names(genres)
    if any(genre.lower() in genres_lower for genre in NSFW_GENRES):
        return True
    tags_lower = _names(tags)
    return any(tag.lower() in tags_lower for tag in NSFW_TAGS)


def resolve_is_nsfw(
    *,
    content_rating: Optional[str] = None,
    is_adult: Optional[bool] = None,
    genres: Optional[Iterable[Any]] = None,
    tags: Optional[Iterable[Any]] = None,
) -> bool:
    """Decide the stored flag for one record.

    A provider rating wins; the genre/tag heuristic is only used when the
    provider did not give a rating at all, so a MangaDex record labeled ``safe``
    is not overridden by a genre name.
    """
    if isinstance(is_adult, bool) and is_adult:
        return True
    if isinstance(content_rating, str) and content_rating.strip():
        return content_rating.strip().lower() in _MANGADEX_ADULT_RATINGS
    return genre_evidence_is_nsfw(genres, tags)


def row_is_nsfw(manga: Any) -> bool:
    """Decide visibility for an ORM row that is already in memory."""
    stored = getattr(manga, "is_nsfw", None)
    if stored is True:
        return True
    return genre_evidence_is_nsfw(
        getattr(manga, "genres", None),
        getattr(manga, "tags", None),
    )


def safety_filter(allow_nsfw: bool = False) -> Optional[str]:
    """The one SQL predicate that decides NSFW visibility.

    Returns ``None`` when the caller asked to include adult titles, so callers
    can simply ``if predicate: where.append(predicate)``. The genre fallback
    stays in the predicate so rows written before the column existed (or by a
    path that forgot to set it) are still hidden.
    """
    if allow_nsfw:
        return None
    return (
        "COALESCE(is_nsfw, false) = false"
        " AND (genres IS NULL OR NOT (genres && ARRAY['Hentai', 'Erotica']))"
    )


BACKFILL_BATCH_SIZE = 500

_BACKFILL_BATCH_SQL = f"""
    WITH batch AS (
        SELECT id FROM manga
        WHERE is_nsfw = false
          AND genres IS NOT NULL
          AND genres && ARRAY['Hentai', 'Erotica']
        LIMIT {BACKFILL_BATCH_SIZE}
    )
    UPDATE manga m SET is_nsfw = true FROM batch WHERE m.id = batch.id
"""


async def backfill_is_nsfw(conn, *, statement_timeout_ms: int = 120_000) -> int:
    """Seed the stored flag for rows that predate it, in small batches.

    Batched on purpose: rewriting a row also rewrites its indexes (including the
    HNSW vector index), so one statement over a large catalog exceeds the app's
    15s statement timeout. The loop is resumable -- it only ever looks at rows
    still marked safe -- so an interrupted run simply continues next start.
    """
    from sqlalchemy import text

    await conn.execute(text(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}"))
    total = 0
    try:
        while True:
            result = await conn.execute(text(_BACKFILL_BATCH_SQL))
            changed = result.rowcount or 0
            total += changed
            if changed == 0:
                break
    finally:
        await conn.execute(text("SET LOCAL statement_timeout TO DEFAULT"))
    return total
