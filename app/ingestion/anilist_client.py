import httpx
from typing import Dict, Any
from .rate_limiter import fetch_with_retry, anilist_bucket

ANILIST_API_URL = "https://graphql.anilist.co"

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
