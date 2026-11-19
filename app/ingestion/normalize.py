from typing import Dict, Any
from datetime import datetime, timezone
import re

from ..services.format import infer_format_type
from ..services.safety import resolve_is_nsfw

def _from_epoch(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _from_iso(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def anilist_to_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    synonyms = raw.get("synonyms") or []
    alt_titles = []
    for s in synonyms:
        if isinstance(s, str) and s.strip():
            clean = s.strip()
            if clean not in alt_titles:
                alt_titles.append(clean)

    return {
        "anilist_id": raw.get("id"),
        "mal_id": raw.get("idMal"),
        "title_romaji": raw.get("title", {}).get("romaji"),
        "title_english": raw.get("title", {}).get("english"),
        "title_native": raw.get("title", {}).get("native"),
        "alternative_titles": alt_titles,
        "synopsis": strip_html_tags(raw.get("description", "")),
        "genres": raw.get("genres", []),
        "tags": raw.get("tags", []),
        "status": raw.get("status"),
        "start_year": raw.get("startDate", {}).get("year"),
        "chapters": raw.get("chapters"),
        "volumes": raw.get("volumes"),
        "average_score": raw.get("averageScore"),
        "popularity": raw.get("popularity"),
        "cover_image_url": raw.get("coverImage", {}).get("large"),
        "banner_image": raw.get("bannerImage"),
        "site_url": raw.get("siteUrl"),
        "source_updated_at": _from_epoch(raw.get("updatedAt")),
        "sync_source": "anilist",
        "format_type": infer_format_type(
            title_native=raw.get("title", {}).get("native"),
            tags=raw.get("tags"),
            genres=raw.get("genres"),
            site_url=raw.get("siteUrl"),
        ),
        "is_nsfw": resolve_is_nsfw(
            is_adult=raw.get("isAdult"),
            genres=raw.get("genres"),
            tags=raw.get("tags"),
        ),
    }

#: MangaDex `originalLanguage` -> publication format.
_ORIGINAL_LANGUAGE_FORMAT = {"ko": "MANHWA", "zh": "MANHUA", "zh-hk": "MANHUA", "ja": "MANGA"}


def mangadex_to_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    attr = raw.get("attributes", {})
    title_dict = attr.get("title", {})
    title_en = title_dict.get("en") or next(iter(title_dict.values()), None)
    
    alt_titles = []
    for item in attr.get("altTitles", []):
        if isinstance(item, dict):
            for val in item.values():
                if isinstance(val, str) and val.strip():
                    clean = val.strip()
                    if clean not in alt_titles:
                        alt_titles.append(clean)
    
    desc_dict = attr.get("description", {})
    synopsis = desc_dict.get("en") or next(iter(desc_dict.values()), "") if desc_dict else ""
    
    tags = []
    genres = []
    for tag_obj in attr.get("tags", []):
        name_en = tag_obj.get("attributes", {}).get("name", {}).get("en")
        if name_en:
            if tag_obj.get("attributes", {}).get("group") == "genre":
                genres.append(name_en)
            else:
                tags.append({"name": name_en, "rank": 100})
                
    # No cover URL on purpose. `uploads.mangadex.org` answers browser image
    # requests with a JS challenge, which an <img> cannot complete, so a MangaDex
    # cover is not a cover - it renders `CoverFallback` for every row it touches.
    # Writing nothing lets the merge keep an AniList/Kitsu cover if one is already
    # stored, and lets the row fall to a generated tile if not. See
    # `app/services/covers.py` and `cover_unavailable_resolve.md`.
    #
    # Returning the URL anyway "for completeness" is exactly how 10,621 dead
    # covers got written; do not restore it without also fixing the render path.
    md_id = raw.get("id")

    return {
        "mangadex_id": md_id,
        "title_romaji": title_en,
        "title_english": title_en,
        "title_native": None,
        "alternative_titles": alt_titles,
        "synopsis": strip_html_tags(synopsis),
        "genres": genres,
        "tags": tags,
        "status": attr.get("status"),
        "start_year": attr.get("year"),
        "chapters": None,
        "volumes": None,
        "average_score": None,
        "popularity": None,
        "cover_image_url": None,
        "site_url": f"https://mangadex.org/title/{md_id}",
        "source_updated_at": _from_iso(attr.get("updatedAt")),
        "sync_source": "mangadex",
        # MangaDex has no native titles, but `originalLanguage` is an explicit
        # Korean/Chinese/Japanese marker — better evidence than tag guessing.
        "format_type": _ORIGINAL_LANGUAGE_FORMAT.get(
            (attr.get("originalLanguage") or "").lower()
        ) or infer_format_type(tags=tags, genres=genres, site_url=f"https://mangadex.org/title/{md_id}"),
        # MangaDex is the only source that publishes an explicit contentRating
        # (safe | suggestive | erotica | pornographic). Ignoring it meant every
        # adult MangaDex title reached the catalog with no NSFW signal at all.
        "is_nsfw": resolve_is_nsfw(
            content_rating=attr.get("contentRating"),
            genres=genres,
            tags=tags,
        ),
    }
