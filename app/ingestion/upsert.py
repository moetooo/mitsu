from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.identity import (
    ExternalId,
    attach_external_ids,
    extract_external_ids,
    find_match,
)
from ..db_models import Manga
from ..enrichment.models import merge_inferred_tags
from ..services.covers import apply_cover_fields, cover_rank
from ..services.format import format_type_for_row, infer_format_type

_EMBEDDING_FIELDS = (
    "title_romaji",
    "title_english",
    "title_native",
    "synopsis",
    "genres",
    "tags",
)


@dataclass
class UpsertResult:
    manga: Manga
    action: str  # inserted | updated | unchanged
    content_changed: bool = False
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def inserted(self) -> bool:
        return self.action == "inserted"


def _embedding_fields_snapshot(manga: Manga) -> dict[str, str]:
    """Frozen view of the fields the embedding is built from."""
    return {
        key: json.dumps(getattr(manga, key, None), sort_keys=True, default=str)
        for key in _EMBEDDING_FIELDS
    }


async def smart_upsert_manga_ex(
    session: AsyncSession,
    record: dict[str, Any],
    *,
    allow_title_fallback: bool = True,
) -> UpsertResult:
    """ID-first upsert that cannot create a second row for a known external ID.

    The old code matched by IDs in an OR and then inserted on any miss. That
    allowed an AniList record and a MangaDex-only row to coexist even when a
    link proved they were the same series. This version resolves identity
    through `manga_external_ids`, attaches new IDs to the canonical row, and
    reports cross-row conflicts instead of inserting.
    """
    record = dict(record)
    record.pop("external_ids", None)
    # Classify once, here, so every write path stores the same thing. Sources
    # that already provide it (normalize.py) keep their value.
    record.setdefault(
        "format_type",
        infer_format_type(
            title_native=record.get("title_native"),
            tags=record.get("tags"),
            genres=record.get("genres"),
            site_url=record.get("site_url"),
            inferred_tags=record.get("inferred_tags"),
        ),
    )
    ids: list[ExternalId] = extract_external_ids(record)
    match = await find_match(session, record, allow_title_fallback=allow_title_fallback)
    conflicts = list(match.conflicts)

    if match.manga is not None:
        existing = match.manga

        # Do not write an ID that is already owned by another manga. That case
        # is a real duplicate pair for the explicit merge command.
        id_conflicts = await attach_external_ids(session, existing.id, ids)
        conflicts.extend(id_conflicts)
        blocked = {(c["source"], c["external_id"]) for c in id_conflicts}
        for item in ids:
            if (item.source, item.external_id) in blocked:
                column = {
                    "anilist": "anilist_id",
                    "mal": "mal_id",
                    "mangadex": "mangadex_id",
                }.get(item.source)
                if column:
                    record.pop(column, None)

        # Compare before/after the merge instead of comparing the raw incoming
        # record to the stored row. A multi-source row holds the union of every
        # source's tags/genres, so the raw-record comparison was false on every
        # sync and re-embedded rows that had not actually changed.
        before = _embedding_fields_snapshot(existing)
        _merge_into(existing, record)
        changed = _embedding_fields_snapshot(existing) != before
        return UpsertResult(
            manga=existing,
            action="updated" if changed else "unchanged",
            content_changed=changed,
            conflicts=conflicts,
        )

    new_manga = Manga(**record)
    # Every cover column comes from the seam (`covers.cover_fields`), so a new row
    # can never carry a URL on a blocked host or a status that disagrees with its
    # URL - the two bugs ingestion used to be able to create independently.
    record_candidates = record.get("cover_candidates")
    record_url = record.get("cover_image_url")
    apply_cover_fields(new_manga, record_url, record_candidates)
    session.add(new_manga)
    await session.flush()
    conflicts.extend(await attach_external_ids(session, new_manga.id, ids))
    return UpsertResult(
        manga=new_manga,
        action="inserted",
        content_changed=True,
        conflicts=conflicts,
    )


async def smart_upsert_manga(session: AsyncSession, record: dict[str, Any]) -> Manga:
    """Backward-compatible wrapper used by the existing ingestion paths."""
    result = await smart_upsert_manga_ex(session, record)
    return result.manga


def _merge_into(existing: Manga, record: dict[str, Any]) -> None:
    # Captured before the merge so cover health is only recomputed when the URL
    # actually changed: re-deriving it unconditionally would erase a `dead`
    # verdict from the verifier every time an unrelated sync ran.
    previous_cover = existing.cover_image_url

    incoming_alts = record.get("alternative_titles") or []
    existing_alts = existing.alternative_titles or []
    seen_alts_lower = {a.lower().strip() for a in existing_alts if a}
    merged_alts = list(existing_alts)
    for alias in incoming_alts:
        if alias and alias.strip() and alias.lower().strip() not in seen_alts_lower:
            merged_alts.append(alias.strip())
            seen_alts_lower.add(alias.lower().strip())
    if incoming_alts:
        existing.alternative_titles = merged_alts

    if record.get("inferred_tags"):
        existing.inferred_tags = merge_inferred_tags(
            existing.inferred_tags or [],
            record.get("inferred_tags") or [],
        )

    if record.get("genres"):
        existing_genres = existing.genres or []
        seen_genres = set(existing_genres)
        merged_genres = list(existing_genres)
        for genre in record["genres"]:
            if genre and genre not in seen_genres:
                merged_genres.append(genre)
                seen_genres.add(genre)
        existing.genres = merged_genres

    if record.get("tags"):
        existing_tags = existing.tags or []
        existing_names = {t.get("name") for t in existing_tags if isinstance(t, dict)}
        merged_tags = list(existing_tags)
        for tag in record["tags"]:
            if isinstance(tag, dict) and tag.get("name") and tag.get("name") not in existing_names:
                merged_tags.append(tag)
                existing_names.add(tag.get("name"))
        existing.tags = merged_tags

    if record.get("is_nsfw"):
        # Safety is monotonic during a merge: one source saying "adult" is
        # enough, and a later "safe" rating must not clear it.
        existing.is_nsfw = True

    # The stored format is derived from exactly these fields, so recomputing it
    # after the merge keeps `format_type` honest when a second source adds the
    # tag that proves a title is a webtoon (ARCH-05).
    if {"title_native", "tags", "genres", "site_url", "inferred_tags"} & set(record):
        existing.format_type = format_type_for_row(existing)

    special_handled = {
        "alternative_titles",
        "inferred_tags",
        "genres",
        "tags",
        "is_nsfw",
        "format_type",  # recomputed above from the merged row, not copied in
    }
    for key, value in record.items():
        if key in special_handled:
            continue
        if key == "source_updated_at":
            current = existing.source_updated_at
            if value is None:
                continue
            if current is not None and _as_utc(current) >= _as_utc(value):
                continue
            existing.source_updated_at = value
            continue
        if key == "last_synced_at":
            if value is not None:
                existing.last_synced_at = value
            continue
        if key in {"title_romaji", "title_english", "title_native"}:
            if not getattr(existing, key, None) and value:
                setattr(existing, key, value)
        elif key == "cover_image_url":
            # Preference, not "first non-empty wins". Previously a MangaDex cover
            # overwrote an AniList one simply by arriving later, which is how a
            # healthy cover became a dead one (cover_unavailable_resolve.md).
            if cover_rank(value) > cover_rank(existing.cover_image_url):
                existing.cover_image_url = value
        elif key in {"synopsis", "banner_image", "site_url"} and not value:
            continue
        elif key in {"anilist_id", "mal_id", "mangadex_id"}:
            current = getattr(existing, key, None)
            if current is not None and value is not None and str(current) != str(value):
                continue
            if value is not None or current is None:
                setattr(existing, key, value)
        elif value is not None or getattr(existing, key, None) is None:
            setattr(existing, key, value)

    if existing.cover_image_url != previous_cover:
        # Re-derive the whole cover block, not just the status: the merge may have
        # gained or lost a fallback without changing which URL is primary.
        apply_cover_fields(existing, existing.cover_image_url, existing.cover_candidates)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
