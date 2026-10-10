from sqlalchemy import select, or_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..db_models import Manga
from ..enrichment.models import merge_inferred_tags

async def smart_upsert_manga(session: AsyncSession, record: dict) -> Manga:
    """
    Intelligent upsert that prevents duplicate records across sources.
    Matches by:
    1. Direct IDs (anilist_id, mal_id, mangadex_id)
    2. Exact title (romaji or english, case-insensitive) + start_year
    Updates existing record if matched, otherwise creates a new row.
    """
    anilist_id = record.get("anilist_id")
    mal_id = record.get("mal_id")
    mangadex_id = record.get("mangadex_id")
    title_romaji = record.get("title_romaji")
    title_english = record.get("title_english")
    start_year = record.get("start_year")

    # 1. Match by external IDs
    id_conditions = []
    if anilist_id is not None:
        id_conditions.append(Manga.anilist_id == anilist_id)
    if mal_id is not None:
        id_conditions.append(Manga.mal_id == mal_id)
    if mangadex_id is not None:
        id_conditions.append(Manga.mangadex_id == mangadex_id)

    existing_manga = None
    if id_conditions:
        stmt = select(Manga).where(or_(*id_conditions))
        res = await session.execute(stmt)
        existing_manga = res.scalars().first()

    # 2. Match by title + start_year if no ID match found
    if not existing_manga and start_year and (title_romaji or title_english):
        titles_to_check = [t.lower().strip() for t in [title_romaji, title_english] if t]
        
        stmt = select(Manga).where(
            Manga.start_year == start_year,
            or_(
                func.lower(Manga.title_romaji).in_(titles_to_check),
                func.lower(Manga.title_english).in_(titles_to_check)
            )
        )
        res = await session.execute(stmt)
        existing_manga = res.scalars().first()

    # 3. Update existing or Insert new
    if existing_manga:
        # Merge alternative titles as deduplicated union
        incoming_alts = record.get("alternative_titles") or []
        existing_alts = existing_manga.alternative_titles or []
        seen_alts_lower = {a.lower().strip() for a in existing_alts if a}
        merged_alts = list(existing_alts)
        for a in incoming_alts:
            if a and a.strip() and a.lower().strip() not in seen_alts_lower:
                merged_alts.append(a.strip())
                seen_alts_lower.add(a.lower().strip())
        existing_manga.alternative_titles = merged_alts

        # Merge inferred tags if provided
        if "inferred_tags" in record and record["inferred_tags"]:
            existing_manga.inferred_tags = merge_inferred_tags(
                existing_manga.inferred_tags or [],
                record.get("inferred_tags") or []
            )

        # Merge genres as deduplicated union
        if "genres" in record and record["genres"]:
            existing_genres = existing_manga.genres or []
            seen_g = set(existing_genres)
            merged_g = list(existing_genres)
            for g in record["genres"]:
                if g and g not in seen_g:
                    merged_g.append(g)
                    seen_g.add(g)
            existing_manga.genres = merged_g

        # Merge raw tags as deduplicated union
        if "tags" in record and record["tags"]:
            existing_tags = existing_manga.tags or []
            existing_names = {t.get("name") for t in existing_tags if isinstance(t, dict)}
            merged_tags = list(existing_tags)
            for t in record["tags"]:
                if isinstance(t, dict) and t.get("name") and t.get("name") not in existing_names:
                    merged_tags.append(t)
                    existing_names.add(t.get("name"))
            existing_manga.tags = merged_tags

        # Update remaining non-empty fields without overwriting existing data with None
        special_handled = {"alternative_titles", "inferred_tags", "genres", "tags"}
        for key, value in record.items():
            if key in special_handled:
                continue
            # Preserve existing titles; do not clobber with None or empty
            if key in {"title_romaji", "title_english", "title_native"}:
                if not getattr(existing_manga, key, None) and value:
                    setattr(existing_manga, key, value)
            elif value is not None or getattr(existing_manga, key, None) is None:
                setattr(existing_manga, key, value)

        return existing_manga
    else:
        new_manga = Manga(**record)
        session.add(new_manga)
        return new_manga

