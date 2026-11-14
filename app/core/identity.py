"""External-id normalisation and attachment to one catalog row.

Lives in `app.core` rather than `app.sync` because the ingestion upsert path
needs it too, and `app.ingestion` must not import `app.sync` (ARCH-02).

The mapping table is authoritative: an id is attached to exactly one manga and
is never moved by this module. A collision is reported as a conflict for the
explicit merge command to resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db_models import Manga, MangaExternalId

# Lower number wins when the same series is found through several providers.
SOURCE_PRIORITY = {
    "anilist": 10,
    "mal": 20,
    "mangadex": 30,
    "kitsu": 40,
    "mangaupdates": 50,
    "bangumi": 60,
}
SOURCE_COLUMN = {
    "anilist": "anilist_id",
    "mal": "mal_id",
    "mangadex": "mangadex_id",
}


@dataclass(frozen=True)
class ExternalId:
    source: str
    external_id: str


@dataclass
class MatchResult:
    manga: Manga | None
    match_kind: str | None = None
    candidate_manga_ids: tuple[int, ...] = ()
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_conflict(self) -> bool:
        return len(self.candidate_manga_ids) > 1


def normalize_external_id(source: str, value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "0"}:
        return None
    if source in {"anilist", "mal", "kitsu", "mangaupdates"}:
        try:
            number = int(text)
        except (TypeError, ValueError):
            return None
        return str(number) if number > 0 else None
    if source == "mangadex":
        return text.lower()
    return text


def extract_external_ids(record: dict[str, Any]) -> list[ExternalId]:
    """Read IDs from both the legacy columns and an optional `external_ids` map."""
    found: dict[tuple[str, str], ExternalId] = {}

    for source, column in SOURCE_COLUMN.items():
        ext = normalize_external_id(source, record.get(column))
        if ext:
            found[(source, ext)] = ExternalId(source, ext)

    extra = record.get("external_ids")
    if isinstance(extra, dict):
        for source, values in extra.items():
            if not isinstance(values, (list, tuple, set)):
                values = [values]
            for value in values:
                ext = normalize_external_id(str(source), value)
                if ext:
                    found[(str(source), ext)] = ExternalId(str(source), ext)

    return sorted(found.values(), key=lambda item: (SOURCE_PRIORITY.get(item.source, 99), item.external_id))


def record_has_external_id(record: dict[str, Any]) -> bool:
    return bool(extract_external_ids(record))


async def attach_external_ids(
    session: AsyncSession,
    manga_id: int,
    ids: list[ExternalId],
    *,
    confidence: float = 1.0,
    touch: bool = True,
) -> list[dict[str, Any]]:
    """Attach IDs to one row without ever moving an ID to another row.

    Returns conflicts where an ID already belongs to a different manga. A
    conflict is data for the explicit merge command, not something this sync
    path should resolve by inserting another row.
    """
    conflicts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    if not ids:
        return conflicts

    # Two queries for the whole call instead of two per ID: the legacy columns
    # are a single OR-ed select and the mapping table a single tuple IN.
    legacy_owner = {
        (source, str(value)): manga_id
        for manga_id, source, value, _priority in await _legacy_id_rows(session, ids)
        if value is not None
    }
    mapped = await _mapping_owners(session, ids)

    for item in ids:
        # Check the legacy column too. The mapping table may not contain an ID
        # that was written by older ingestion code, and writing it here would
        # violate the single-column unique index.
        column = SOURCE_COLUMN.get(item.source)
        if column:
            legacy_owner_id = legacy_owner.get((item.source, item.external_id))
            if legacy_owner_id is not None and legacy_owner_id != manga_id:
                conflicts.append({
                    "source": item.source,
                    "external_id": item.external_id,
                    "existing_manga_id": legacy_owner_id,
                    "wanted_manga_id": manga_id,
                })
                continue

        existing = mapped.get((item.source, item.external_id))
        if existing is None:
            session.add(MangaExternalId(
                manga_id=manga_id,
                source=item.source,
                external_id=item.external_id,
                confidence=confidence,
                first_seen_at=now,
                last_seen_at=now,
            ))
            mapped[(item.source, item.external_id)] = manga_id
        elif existing == manga_id:
            if touch:
                await _touch_mapping(session, item, confidence=confidence, now=now)
        else:
            conflicts.append({
                "source": item.source,
                "external_id": item.external_id,
                "existing_manga_id": existing,
                "wanted_manga_id": manga_id,
            })

    return conflicts


async def _touch_mapping(
    session: AsyncSession,
    item: ExternalId,
    *,
    confidence: float,
    now: datetime,
) -> None:
    row = await session.scalar(
        select(MangaExternalId).where(
            MangaExternalId.source == item.source,
            MangaExternalId.external_id == item.external_id,
        )
    )
    if row is None:
        return
    row.last_seen_at = now
    row.confidence = max(float(row.confidence or 1.0), confidence)


async def _mapping_owners(
    session: AsyncSession,
    ids: list[ExternalId],
) -> dict[tuple[str, str], int]:
    """(source, external_id) -> manga_id for every mapping row that exists."""
    if not ids:
        return {}
    result = await session.execute(
        select(MangaExternalId.source, MangaExternalId.external_id, MangaExternalId.manga_id)
        .where(tuple_(MangaExternalId.source, MangaExternalId.external_id).in_(
            [(item.source, item.external_id) for item in ids]
        ))
    )
    return {(source, external_id): manga_id for source, external_id, manga_id in result.all()}


async def _legacy_id_rows(
    session: AsyncSession,
    ids: list[ExternalId],
) -> list[tuple[int, str, Any, int]]:
    """Every (manga_id, source, value, priority) whose legacy column holds one of `ids`.

    One query, so callers do not pay a round trip per external ID. The priority
    is the row's own best-provider rank, which is what the old per-column probe
    plus re-read computed in two statements.
    """
    conditions = _legacy_conditions(ids)
    if not conditions:
        return []

    result = await session.execute(
        select(Manga.id, Manga.anilist_id, Manga.mal_id, Manga.mangadex_id).where(or_(*conditions))
    )

    wanted = {(item.source, item.external_id) for item in ids}
    found: list[tuple[int, str, Any, int]] = []
    for row in result.all():
        priority = _row_priority(row.anilist_id, row.mal_id, row.mangadex_id)
        for source, value in (
            ("anilist", row.anilist_id),
            ("mal", row.mal_id),
            ("mangadex", row.mangadex_id),
        ):
            if value is None:
                continue
            if (source, str(value)) in wanted:
                found.append((row.id, source, value, priority))
    return found


def _legacy_conditions(ids: list[ExternalId]) -> list[Any]:
    conditions = []
    for item in ids:
        column = SOURCE_COLUMN.get(item.source)
        if not column:
            continue
        conditions.append(getattr(Manga, column) == _typed_id(item))
    return conditions


async def find_match(
    session: AsyncSession,
    record: dict[str, Any],
    *,
    allow_title_fallback: bool = True,
) -> MatchResult:
    """ID-first identity resolution.

    Order:
      1. `manga_external_ids` (authoritative, prevents duplicate inserts)
      2. legacy ID columns (works before the mapping seed)
      3. exact normalized title + same start_year (last resort)

    Multiple ID matches are reported as a conflict. The caller picks the
    highest-priority row (AniList first) and never inserts a new one.
    """
    ids = extract_external_ids(record)
    if not ids:
        if allow_title_fallback:
            return await _title_year_match(session, record, ids)
        return MatchResult(manga=None)

    candidate_priority: dict[int, int] = {}
    candidate_evidence: dict[int, set[tuple[str, str]]] = {}

    mapped = await _mapping_owners(session, ids)
    for item in ids:
        mapped_id = mapped.get((item.source, item.external_id))
        if mapped_id is not None:
            candidate_priority[mapped_id] = min(
                candidate_priority.get(mapped_id, 999),
                SOURCE_PRIORITY.get(item.source, 99),
            )
            candidate_evidence.setdefault(mapped_id, set()).add((item.source, item.external_id))

    # One query returns both the owners and the columns the priority depends on,
    # instead of probing the columns and then re-reading the same rows.
    for manga_id, _source, _value, priority in await _legacy_id_rows(session, ids):
        candidate_priority[manga_id] = min(candidate_priority.get(manga_id, 999), priority)
        candidate_evidence.setdefault(manga_id, set())

    if not candidate_priority:
        if allow_title_fallback:
            return await _title_year_match(session, record, ids)
        return MatchResult(manga=None)

    ordered = sorted(
        candidate_priority,
        key=lambda manga_id: (candidate_priority[manga_id], manga_id),
    )
    canonical_id = ordered[0]
    # The ORM still declares a composite PK for the old partitioned model;
    # production has only `id` as a PK, so query by id explicitly.
    canonical = await session.scalar(select(Manga).where(Manga.id == canonical_id))

    conflicts: list[dict[str, Any]] = []
    if len(ordered) > 1:
        for other_id in ordered[1:]:
            for source, external_id in sorted(candidate_evidence.get(other_id, set())):
                conflicts.append({
                    "source": source,
                    "external_id": external_id,
                    "existing_manga_id": other_id,
                    "canonical_manga_id": canonical_id,
                })

    return MatchResult(
        manga=canonical,
        match_kind="external_id",
        candidate_manga_ids=tuple(ordered),
        conflicts=conflicts,
    )



def _typed_id(item: ExternalId) -> Any:
    if item.source in {"anilist", "mal", "kitsu", "mangaupdates"}:
        return int(item.external_id)
    return item.external_id


def _row_priority(anilist_id: Any, mal_id: Any, mangadex_id: Any) -> int:
    if anilist_id:
        return SOURCE_PRIORITY["anilist"]
    if mal_id:
        return SOURCE_PRIORITY["mal"]
    if mangadex_id:
        return SOURCE_PRIORITY["mangadex"]
    return 999


async def _title_year_match(
    session: AsyncSession,
    record: dict[str, Any],
    ids: list[ExternalId],
) -> MatchResult:
    start_year = record.get("start_year")
    raw_titles = [record.get("title_romaji"), record.get("title_english")]
    titles = sorted({t.strip().lower() for t in raw_titles if isinstance(t, str) and t.strip()})
    if not start_year or not titles:
        return MatchResult(manga=None)

    rows = await session.execute(
        select(Manga).where(
            Manga.start_year == start_year,
            or_(
                func.lower(func.trim(Manga.title_romaji)).in_(titles),
                func.lower(func.trim(Manga.title_english)).in_(titles),
            ),
        ).order_by(Manga.id).limit(2)
    )
    matches = rows.scalars().all()
    if not matches:
        return MatchResult(manga=None)
    return MatchResult(
        manga=matches[0],
        match_kind="title_year",
        candidate_manga_ids=tuple(m.id for m in matches),
        conflicts=[] if len(matches) == 1 else [{
            "reason": "multiple_title_year_matches",
            "manga_ids": [m.id for m in matches],
        }],
    )
