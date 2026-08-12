from typing import Dict, Any
import re

def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def anilist_to_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "anilist_id": raw.get("id"),
        "mal_id": raw.get("idMal"),
        "title_romaji": raw.get("title", {}).get("romaji"),
        "title_english": raw.get("title", {}).get("english"),
        "title_native": raw.get("title", {}).get("native"),
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
        "site_url": raw.get("siteUrl")
    }

def jikan_to_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    published_from = raw.get("published", {}).get("from")
    start_year = int(published_from[:4]) if published_from and len(published_from) >= 4 else None
    genres = [g.get("name") for g in raw.get("genres", []) if g.get("name")]
    tags = [{"name": t.get("name"), "rank": 100} for t in raw.get("themes", []) if t.get("name")]
    
    return {
        "mal_id": raw.get("mal_id"),
        "title_romaji": raw.get("title"),
        "title_english": raw.get("title_english"),
        "title_native": raw.get("title_japanese"),
        "synopsis": strip_html_tags(raw.get("synopsis", "")),
        "genres": genres,
        "tags": tags,
        "status": raw.get("status"),
        "start_year": start_year,
        "chapters": raw.get("chapters"),
        "volumes": raw.get("volumes"),
        "average_score": int(raw.get("score") * 10) if raw.get("score") else None,
        "popularity": raw.get("members"),
        "cover_image_url": raw.get("images", {}).get("jpg", {}).get("large_image_url"),
        "site_url": raw.get("url")
    }

def mangadex_to_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    attr = raw.get("attributes", {})
    title_dict = attr.get("title", {})
    title_en = title_dict.get("en") or next(iter(title_dict.values()), None)
    
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
                
    cover_file = None
    for rel in raw.get("relationships", []):
        if rel.get("type") == "cover_art":
            cover_file = rel.get("attributes", {}).get("fileName")
            break
    
    md_id = raw.get("id")
    cover_url = f"https://uploads.mangadex.org/covers/{md_id}/{cover_file}" if cover_file else None

    return {
        "mangadex_id": md_id,
        "title_romaji": title_en,
        "title_english": title_en,
        "title_native": None,
        "synopsis": strip_html_tags(synopsis),
        "genres": genres,
        "tags": tags,
        "status": attr.get("status"),
        "start_year": attr.get("year"),
        "chapters": None,
        "volumes": None,
        "average_score": None,
        "popularity": None,
        "cover_image_url": cover_url,
        "site_url": f"https://mangadex.org/title/{md_id}"
    }
