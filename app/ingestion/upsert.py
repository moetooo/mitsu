from sqlalchemy import select, or_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..db_models import Manga

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
        # Merge/update fields if record provides them
        for key, value in record.items():
            if value is not None or getattr(existing_manga, key, None) is None:
                setattr(existing_manga, key, value)
        return existing_manga
    else:
        new_manga = Manga(**record)
        session.add(new_manga)
        return new_manga
