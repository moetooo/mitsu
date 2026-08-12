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
