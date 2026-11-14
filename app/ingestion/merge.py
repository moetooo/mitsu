"""Cross-source merge pass.

"Merge" used to be a raw ``DELETE`` of the duplicate row: every tag, synopsis,
score, ``similar_mangas`` edge and ``manga_external_ids`` mapping on that row was
destroyed, and any row that pointed at it was left dangling. This version keeps
the surviving row, folds the duplicate's fields into it, repoints the rows that
referenced it, and only then deletes it.

It is a dry run by default: the pass builds the whole plan, reports what would
move, and rolls back. ``python -m app.ingestion.merge --apply`` is the only way
to write.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy import delete, select, text

from ..db import AsyncSessionLocal
from ..db_models import Manga
from ..services.safety import genre_evidence_is_nsfw

logger = logging.getLogger("mitsu.ingestion.merge")

# Fields that are not merged column-by-column.
_NOT_MERGED = {"id", "created_at", "updated_at", "embedding", "similar_mangas"}


def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    l1, l2 = len(a), len(b)
    if abs(l1 - l2) / max(l1, l2) > 0.10:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def clean_title(t: str) -> str:
    if not t:
        return ""
    return t.lower().strip()


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return not value
    return False


def _merge_duplicate_into(keep: Manga, drop: Manga) -> None:
    """Fold ``drop`` into ``keep``. The surviving row wins on conflicts."""
    # Union the categorical fields.
    for key in ("genres", "alternative_titles"):
        merged = list(getattr(keep, key) or [])
        seen = {str(item).lower() for item in merged}
        for item in getattr(drop, key) or []:
            marker = str(item).lower()
            if item and marker not in seen:
                merged.append(item)
                seen.add(marker)
        if merged:
            setattr(keep, key, merged)

    tags = list(keep.tags or [])
    tag_names = {t.get("name") for t in tags if isinstance(t, dict)}
    for tag in drop.tags or []:
        if isinstance(tag, dict) and tag.get("name") and tag["name"] not in tag_names:
            tags.append(tag)
            tag_names.add(tag["name"])
    if tags:
        keep.tags = tags

    inferred = list(keep.inferred_tags or [])
    known = {t.get("slug") for t in inferred if isinstance(t, dict)}
    for tag in drop.inferred_tags or []:
        if isinstance(tag, dict) and tag.get("slug") and tag["slug"] not in known:
            inferred.append(tag)
            known.add(tag["slug"])
    if inferred:
        keep.inferred_tags = inferred

    # Fill gaps only; never overwrite a value the surviving row already has.
    for column in Manga.__table__.columns:
        key = column.key
        if key in _NOT_MERGED or key in {"genres", "alternative_titles", "tags", "inferred_tags"}:
            continue
        if key in {"anilist_id", "mal_id", "mangadex_id"}:
            # Unique columns are filled after the duplicate row is deleted (see
            # _fill_external_id_columns); copying them now would collide with
            # the row that still owns the value.
            continue
        if key == "is_nsfw":
            keep.is_nsfw = bool(keep.is_nsfw or getattr(drop, "is_nsfw", False))
            continue
        if _empty(getattr(keep, key)) and not _empty(getattr(drop, key)):
            setattr(keep, key, getattr(drop, key))

    # Keep the better score and the larger counts.
    for key in ("average_score", "popularity", "chapters", "volumes"):
        current = getattr(keep, key)
        incoming = getattr(drop, key)
        if incoming is not None and (current is None or incoming > current):
            setattr(keep, key, incoming)

    if getattr(keep, "source_updated_at", None) is None:
        keep.source_updated_at = getattr(drop, "source_updated_at", None)
    if getattr(keep, "embedding", None) is None:
        keep.embedding = getattr(drop, "embedding", None)

    if not keep.is_nsfw and genre_evidence_is_nsfw(drop.genres, drop.tags):
        keep.is_nsfw = True


def _fill_external_id_columns(keep: Manga, drop: Manga) -> None:
    """Inherit a duplicate's unique id columns once it has been deleted."""
    for column in ("anilist_id", "mal_id", "mangadex_id"):
        if getattr(keep, column, None) is None and getattr(drop, column, None) is not None:
            setattr(keep, column, getattr(drop, column))


def _merge_similar_edges(keep: Manga, drop: Manga, resolve) -> int:
    """Union the duplicate's precomputed edges into the surviving row."""
    if not drop.similar_mangas:
        return 0
    edges: dict[int, float] = {}
    for edge in keep.similar_mangas or []:
        if isinstance(edge, dict) and isinstance(edge.get("id"), int):
            edges[edge["id"]] = float(edge.get("score") or 0.0)
    for edge in drop.similar_mangas or []:
        if not isinstance(edge, dict) or not isinstance(edge.get("id"), int):
            continue
        target = resolve(edge["id"])
        if target == keep.id:
            continue
        edges[target] = max(edges.get(target, 0.0), float(edge.get("score") or 0.0))
    merged = [{"id": key, "score": score} for key, score in sorted(edges.items())]
    if merged != (keep.similar_mangas or []):
        keep.similar_mangas = merged
        return len(merged)
    return 0


def _plan_mal_pairs(rows: Iterable[Any]) -> list[tuple[int, int, str]]:
    keep_by_mal: dict[Any, int] = {}
    pairs: list[tuple[int, int, str]] = []
    for row in rows:
        if row.mal_id and row.anilist_id:
            keep_by_mal[row.mal_id] = row.id
    for row in rows:
        if row.mal_id and not row.anilist_id and row.mal_id in keep_by_mal:
            pairs.append((keep_by_mal[row.mal_id], row.id, "mal_id"))
    return pairs


def _plan_title_year_pairs(rows: Iterable[Any]) -> list[tuple[int, int, str]]:
    seen: dict[tuple[str, Any], int] = {}
    pairs: list[tuple[int, int, str]] = []
    for row in rows:
        title = clean_title(row.title_english or row.title_romaji)
        if not title or not row.start_year:
            continue
        key = (title, row.start_year)
        if key in seen:
            pairs.append((seen[key], row.id, "title_year"))
        else:
            seen[key] = row.id
    return pairs


def _plan_fuzzy_pairs(rows: Iterable[Any]) -> list[tuple[int, int, str]]:
    buckets: dict[Any, list[Any]] = defaultdict(list)
    for row in rows:
        if row.start_year:
            buckets[row.start_year].append(row)

    pairs: list[tuple[int, int, str]] = []
    for year in sorted(buckets):
        items = buckets[year]
        if len(items) < 2:
            continue
        for i in range(len(items)):
            first = items[i]
            title_first = clean_title(first.title_english or first.title_romaji)
            if not title_first:
                continue
            for j in range(i + 1, len(items)):
                second = items[j]
                title_second = clean_title(second.title_english or second.title_romaji)
                if not title_second:
                    continue
                if similarity_ratio(title_first, title_second) >= 0.90:
                    pairs.append((first.id, second.id, "fuzzy_title"))
    return pairs


def build_plan(rows: Iterable[Any]) -> tuple[dict[int, int], dict[str, int]]:
    """Resolve every duplicate to one surviving row.

    Chains are collapsed, so a row can never be both a survivor and a deletion.
    """
    keep_of: dict[int, int] = {}
    counts = {"mal_id": 0, "title_year": 0, "fuzzy_title": 0}

    def resolve(row_id: int) -> int:
        seen = set()
        while row_id in keep_of and row_id not in seen:
            seen.add(row_id)
            row_id = keep_of[row_id]
        return row_id

    for keep_id, drop_id, reason in (
        _plan_mal_pairs(rows) + _plan_title_year_pairs(rows) + _plan_fuzzy_pairs(rows)
    ):
        survivor = resolve(keep_id)
        # Already collapsed into the same survivor (chain), or a self-pair.
        if survivor == drop_id or resolve(drop_id) == survivor:
            continue
        keep_of[drop_id] = survivor
        counts[reason] += 1

    return keep_of, counts


async def _merge_and_report(
    session,
    keep_of: dict[int, int],
    counts: dict[str, int],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    if not keep_of:
        return {
            "dry_run": dry_run,
            "pairs": 0,
            "reasons": counts,
            "affected_external_ids": 0,
            "affected_similar_edges": 0,
            "rows_deleted": 0,
            "sample": [],
        }

    def resolve(row_id: int) -> int:
        seen = set()
        while row_id in keep_of and row_id not in seen:
            seen.add(row_id)
            row_id = keep_of[row_id]
        return row_id

    pairs = [(resolve(drop), drop) for drop in keep_of]

    # The map lives in a temp table so the repointing statements are single
    # set-based queries instead of one scan per duplicate.
    await session.execute(text(
        "CREATE TEMP TABLE IF NOT EXISTS merge_map ("
        "keep_id integer NOT NULL, drop_id integer NOT NULL) ON COMMIT DROP"
    ))
    await session.execute(
        text("INSERT INTO merge_map (keep_id, drop_id) VALUES (:keep_id, :drop_id)"),
        [{"keep_id": keep, "drop_id": drop} for keep, drop in pairs],
    )

    affected_external_ids = await session.scalar(text(
        "SELECT count(*) FROM manga_external_ids e JOIN merge_map m ON m.drop_id = e.manga_id"
    ))
    affected_similar_edges = await session.scalar(text(
        """
        SELECT count(*)
        FROM manga m
        WHERE jsonb_typeof(m.similar_mangas) = 'array'
          AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(m.similar_mangas) AS elem
            JOIN merge_map mm ON mm.drop_id = (elem->>'id')::int
          )
        """
    ))

    keep_ids = {keep for keep, _ in pairs}
    drop_ids = {drop for _, drop in pairs}
    keeps = {
        row.id: row
        for row in (await session.execute(
            select(Manga).where(Manga.id.in_(keep_ids))
        )).scalars()
    }
    drops = {
        row.id: row
        for row in (await session.execute(
            select(Manga).where(Manga.id.in_(drop_ids))
        )).scalars()
    }

    merged_rows = 0
    for keep_id, drop_id in pairs:
        keep, drop = keeps.get(keep_id), drops.get(drop_id)
        if keep is None or drop is None:
            logger.warning(
                "[Merge] Skipping pair %s <- %s: row disappeared during the pass",
                keep_id,
                drop_id,
            )
            continue
        _merge_duplicate_into(keep, drop)
        _merge_similar_edges(keep, drop, resolve)
        merged_rows += 1

    # Repoint every reference to the duplicate before deleting it.
    await session.execute(text(
        """
        DELETE FROM manga_external_ids d
        USING manga_external_ids k, merge_map m
        WHERE d.manga_id = m.drop_id
          AND k.manga_id = m.keep_id
          AND d.source = k.source
          AND d.external_id = k.external_id
        """
    ))
    await session.execute(text(
        """
        UPDATE manga_external_ids e
        SET manga_id = m.keep_id
        FROM merge_map m
        WHERE e.manga_id = m.drop_id
        """
    ))
    await session.execute(text(
        """
        UPDATE manga
        SET similar_mangas = (
            SELECT jsonb_agg(DISTINCT jsonb_build_object(
                       'id', COALESCE(mm.keep_id, (elem->>'id')::int),
                       'score', COALESCE((elem->>'score')::float, 0)))
            FROM jsonb_array_elements(manga.similar_mangas) AS elem
            LEFT JOIN merge_map mm ON mm.drop_id = (elem->>'id')::int
            WHERE COALESCE(mm.keep_id, (elem->>'id')::int) <> manga.id
        )
        WHERE jsonb_typeof(similar_mangas) = 'array'
          AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(manga.similar_mangas) AS elem
            JOIN merge_map mm ON mm.drop_id = (elem->>'id')::int
          )
        """
    ))

    # Detach the duplicates before the bulk DELETE so the ORM does not try to
    # flush them again, then inherit their unique id columns on the survivors.
    for row in drops.values():
        session.expunge(row)
    result = await session.execute(delete(Manga).where(Manga.id.in_(drop_ids)))
    rows_deleted = result.rowcount or 0
    for keep_id, drop_id in pairs:
        keep, drop = keeps.get(keep_id), drops.get(drop_id)
        if keep is not None and drop is not None:
            _fill_external_id_columns(keep, drop)

    report = {
        "dry_run": dry_run,
        "pairs": len(pairs),
        "reasons": counts,
        "merged_rows": merged_rows,
        "affected_external_ids": int(affected_external_ids or 0),
        "affected_similar_edges": int(affected_similar_edges or 0),
        "rows_deleted": rows_deleted,
        "sample": [
            {"keep_id": keep, "drop_id": drop} for keep, drop in pairs[:25]
        ],
    }
    return report


async def run_merge_pass(dry_run: bool = True) -> dict[str, Any]:
    logger.info("[Merge Pass] Starting cross-source deduplication (dry_run=%s)...", dry_run)
    async with AsyncSessionLocal() as session:
        stmt = select(
            Manga.id,
            Manga.title_english,
            Manga.title_romaji,
            Manga.start_year,
            Manga.anilist_id,
            Manga.mal_id,
            Manga.mangadex_id,
        )
        rows = (await session.execute(stmt)).all()
        logger.info("[Merge Pass] Loaded %d lightweight records.", len(rows))

        keep_of, counts = build_plan(rows)
        report = await _merge_and_report(session, keep_of, counts, dry_run=dry_run)

        if dry_run:
            await session.rollback()
            logger.info(
                "[Merge Pass] DRY RUN: %d duplicate rows would merge; "
                "%d external-id rows and %d similar-edge rows would move. "
                "Nothing was written. Re-run with --apply to commit.",
                report["pairs"],
                report["affected_external_ids"],
                report["affected_similar_edges"],
            )
        else:
            await session.commit()
            logger.info(
                "[Merge Pass] Merged %d duplicate rows (%s); repointed %d external ids "
                "and %d similar-edge rows.",
                report["rows_deleted"],
                ", ".join(f"{k}={v}" for k, v in counts.items()),
                report["affected_external_ids"],
                report["affected_similar_edges"],
            )
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the merge; without this flag the pass only reports",
    )
    args = parser.parse_args(argv)
    asyncio.run(run_merge_pass(dry_run=not args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
