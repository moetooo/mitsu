from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
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

    for item in ids:
        # Check the legacy column too. The mapping table may not contain an ID
        # that was written by older ingestion code, and writing it here would
        # violate the single-column unique index.
        column = SOURCE_COLUMN.get(item.source)
        if column:
            legacy_owner = await session.scalar(
                select(Manga.id).where(getattr(Manga, column) == _typed_id(item))
            )
            if legacy_owner is not None and legacy_owner != manga_id:
                conflicts.append({
                    "source": item.source,
                    "external_id": item.external_id,
                    "existing_manga_id": legacy_owner,
                    "wanted_manga_id": manga_id,
                })
                continue

        existing = await session.scalar(
            select(MangaExternalId).where(
                MangaExternalId.source == item.source,
                MangaExternalId.external_id == item.external_id,
            )
        )
        if existing is None:
            session.add(MangaExternalId(
                manga_id=manga_id,
                source=item.source,
                external_id=item.external_id,
                confidence=confidence,
                first_seen_at=now,
                last_seen_at=now,
            ))
        elif existing.manga_id == manga_id:
            if touch:
                existing.last_seen_at = now
                existing.confidence = max(float(existing.confidence or 1.0), confidence)
        else:
            conflicts.append({
                "source": item.source,
                "external_id": item.external_id,
                "existing_manga_id": existing.manga_id,
                "wanted_manga_id": manga_id,
            })

    return conflicts


async def _column_matches(session: AsyncSession, ids: list[ExternalId]) -> dict[str, list[int]]:
    conditions = []
    for item in ids:
        column = SOURCE_COLUMN.get(item.source)
        if not column:
            continue
        if item.source in {"anilist", "mal"}:
            conditions.append(getattr(Manga, column) == int(item.external_id))
        else:
            conditions.append(getattr(Manga, column) == item.external_id)

    if not conditions:
        return {}

    result = await session.execute(select(Manga.id).where(or_(*conditions)))
    return {item.source: [row[0] for row in result.all()] for item in ids}


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

    for item in ids:
        mapped = await session.scalar(
            select(MangaExternalId.manga_id).where(
                MangaExternalId.source == item.source,
                MangaExternalId.external_id == item.external_id,
            )
        )
        if mapped is not None:
            candidate_priority[mapped] = min(
                candidate_priority.get(mapped, 999),
                SOURCE_PRIORITY.get(item.source, 99),
            )
            candidate_evidence.setdefault(mapped, set()).add((item.source, item.external_id))

    legacy = await _column_matches(session, ids)
    if any(legacy.values()):
        legacy_conditions = []
        for item in ids:
            column = SOURCE_COLUMN.get(item.source)
            if not column:
                continue
            if item.source in {"anilist", "mal"}:
                legacy_conditions.append(getattr(Manga, column) == int(item.external_id))
            else:
                legacy_conditions.append(getattr(Manga, column) == item.external_id)
        if legacy_conditions:
            rows = await session.execute(
                select(Manga.id, Manga.anilist_id, Manga.mal_id, Manga.mangadex_id).where(or_(*legacy_conditions))
            )
            for row in rows.all():
                candidate_priority[row.id] = min(
                    candidate_priority.get(row.id, 999),
                    _row_priority(row.anilist_id, row.mal_id, row.mangadex_id),
                )
                candidate_evidence.setdefault(row.id, set())

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
