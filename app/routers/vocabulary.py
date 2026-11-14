"""Read-only controlled vocabulary for the client.

The UI kept three hand-copied option lists (the filter drawer's categories, the
trending genre pills, the trending format pills) and the server kept a fourth
reading of the same thing. They drifted: the drawer offered "Boys' Love" while a
pinned list offered "Yaoi", which the catalogue matches as a synonym at best.

The canonical list already exists in `app/enrichment/vocabulary.py`. This serves
it so the client cannot invent entries, and so an entitlement to a new genre is a
one-line change in one place.

Read-only, no database, no auth: it is static data behind a cache header.
"""

from fastapi import APIRouter, Response
from typing import Dict, List

from pydantic import BaseModel

from ..enrichment.vocabulary import TagCategory, list_all_tags

router = APIRouter()

# Bumped when the taxonomy changes in a way the client should notice. The client
# caches by this number, so a stale localStorage entry cannot outlive a change.
VOCABULARY_VERSION = 1

# Human labels for the filter drawer's groups. The order of this mapping is the
# order the UI renders them in.
CATEGORY_LABELS: Dict[TagCategory, str] = {
    TagCategory.GENRE: "Core Genres",
    TagCategory.DEMOGRAPHIC: "Demographics",
    TagCategory.RELATIONSHIP: "Romance & Relationships",
    TagCategory.THEME: "Themes",
    TagCategory.SETTING: "Settings & World",
    TagCategory.TROPE: "Story Tropes",
}


# The only format values ingestion actually writes into `format_type`
# (app/ingestion/normalize.py maps original language -> MANGA / MANHWA / MANHUA).
# A format the catalogue never holds is served with filterable=False so the client
# does not offer a pill that can only ever return an empty shelf.
CATALOGUE_FORMATS = ("manga", "manhwa", "manhua")


class VocabularyOption(BaseModel):
    slug: str
    # `value` is what a filter sends. The retrieval layer matches canonical
    # display names (`Boys' Love`, `Sci-Fi`), not slugs, so this is the name.
    value: str
    label: str
    description: str = ""
    # Only meaningful for formats: whether the catalogue can filter on it.
    filterable: bool = True


class VocabularyGroup(BaseModel):
    id: str
    label: str
    options: List[VocabularyOption]


class VocabularyResponse(BaseModel):
    version: int
    categories: List[VocabularyGroup]
    formats: List[VocabularyOption]


def _option(tag) -> VocabularyOption:
    return VocabularyOption(
        slug=tag.slug,
        value=tag.name,
        label=tag.name,
        description=tag.description,
        filterable=tag.slug in CATALOGUE_FORMATS if tag.category == TagCategory.FORMAT else True,
    )


def build_vocabulary() -> VocabularyResponse:
    """The response body, derived from the canonical list. Pure, so it is testable."""
    tags = list_all_tags()
    categories: List[VocabularyGroup] = []
    for category, label in CATEGORY_LABELS.items():
        options = [_option(tag) for tag in tags if tag.category == category]
        if options:
            categories.append(VocabularyGroup(id=category.value, label=label, options=options))

    formats = [_option(tag) for tag in tags if tag.category == TagCategory.FORMAT]
    return VocabularyResponse(version=VOCABULARY_VERSION, categories=categories, formats=formats)


@router.get("/vocabulary", response_model=VocabularyResponse)
async def get_vocabulary(response: Response) -> VocabularyResponse:
    """The genre/theme/format vocabulary the filters and pills are built from."""
    response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=300"
    return build_vocabulary()
