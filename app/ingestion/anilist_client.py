import httpx
from typing import Dict, Any
from .rate_limiter import fetch_with_retry, anilist_bucket

ANILIST_API_URL = "https://graphql.anilist.co"

# Hard server-side pagination ceiling: page * perPage may not exceed 5000.
# The API still advertises a lastPage just past it, so callers must treat a
# 400 "Page depth exceeds maximum" as "no deeper page exists".
ANILIST_PAGE_DEPTH_LIMIT = 5000
ANILIST_PAGE_DEPTH_ERROR = "Page depth exceeds maximum"

QUERY = """
query ($page: Int, $perPage: Int, $startDateGreater: FuzzyDateInt, $startDateLesser: FuzzyDateInt) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total currentPage lastPage hasNextPage }
    media(type: MANGA, sort: POPULARITY_DESC, startDate_greater: $startDateGreater, startDate_lesser: $startDateLesser) {
      id
      idMal
      title { romaji english native }
      description(asHtml: false)
      genres
      tags { name rank }
      status
      startDate { year month day }
      chapters
      volumes
      averageScore
      popularity
      synonyms
      coverImage { large medium color }
      bannerImage
      siteUrl
    }
  }
}
"""

async def fetch_page(page: int, per_page: int = 50, start_date_greater: int = None, start_date_lesser: int = None) -> Dict[str, Any]:
    variables = {"page": page, "perPage": per_page}
    if start_date_greater:
        variables["startDateGreater"] = start_date_greater
    if start_date_lesser:
        variables["startDateLesser"] = start_date_lesser

    async with httpx.AsyncClient() as client:
        def raw_post():
            return client.post(
                ANILIST_API_URL,
                json={"query": QUERY, "variables": variables},
                timeout=15.0
            )
        
        json_data = await fetch_with_retry(anilist_bucket, raw_post)
        return json_data["data"]["Page"]

UPDATED_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total currentPage lastPage hasNextPage }
    media(type: MANGA, sort: UPDATED_AT_DESC) {
      id
      idMal
      updatedAt
      title { romaji english native }
      description(asHtml: false)
      genres
      tags { name rank }
      status
      startDate { year month day }
      chapters
      volumes
      averageScore
      popularity
      synonyms
      coverImage { large medium color }
      bannerImage
      siteUrl
    }
  }
}
"""


async def fetch_updated_page(
    page: int,
    per_page: int = 50,
    *,
    max_retries: int = 2,
    before_request=None,
) -> Dict[str, Any]:
    """Fetch one page of recently updated manga, newest first.

    AniList has no `updatedAt_greater` filter, so the sync uses this sort and
    stops once a page is older than the stored checkpoint.
    """
    variables = {"page": page, "perPage": per_page}

    async with httpx.AsyncClient() as client:
        def raw_post():
            return client.post(
                ANILIST_API_URL,
                json={"query": UPDATED_QUERY, "variables": variables},
                timeout=20.0,
                headers={"User-Agent": "Mitsu/1.0 (catalog sync)"},
            )

        json_data = await fetch_with_retry(
            anilist_bucket,
            raw_post,
            max_retries=max_retries,
            before_request=before_request,
        )
        return json_data["data"]["Page"]


# Cover-only lookup by id. A repair run already knows which titles it wants, so it
# must not re-walk popularity pages: `id_in` answers 50 ids per request, and the
# response carries just the two fields a cover decision needs.
COVER_BY_IDS_QUERY = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(id_in: $ids, type: MANGA) {
      id
      coverImage { large medium }
    }
  }
}
"""


async def fetch_covers_by_ids(anilist_ids) -> Dict[int, Dict[str, Any]]:
    """`{anilist_id: {"large": url, "medium": url}}` for ids AniList still knows.

    Ids that no longer exist are absent from the result rather than empty, so the
    caller must not assume one entry per id.
    """
    ids = [int(i) for i in anilist_ids if i]
    if not ids:
        return {}

    async with httpx.AsyncClient() as client:
        def raw_post():
            return client.post(
                ANILIST_API_URL,
                json={"query": COVER_BY_IDS_QUERY, "variables": {"ids": ids[:50]}},
                timeout=15.0,
            )

        json_data = await fetch_with_retry(anilist_bucket, raw_post)

    media = (json_data.get("data") or {}).get("Page", {}).get("media") or []
    found: Dict[int, Dict[str, Any]] = {}
    wanted = set(ids)
    for item in media:
        media_id = item.get("id")
        if media_id in wanted:
            cover = item.get("coverImage") or {}
            found[int(media_id)] = {
                "large": cover.get("large"),
                "medium": cover.get("medium"),
            }
    return found
