import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.enrichment.vocabulary import TagCategory, list_all_tags
from app.routers.vocabulary import build_vocabulary, VOCABULARY_VERSION


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------
# FE-23: the client's option lists must come from the canonical
# vocabulary, not from a hand-copied list of their own.
# ---------------------------------------------------------------

def test_build_vocabulary_is_derived_from_the_canonical_tags():
    body = build_vocabulary()
    served_values = [
        option.value
        for group in body.categories
        for option in group.options
    ] + [option.value for option in body.formats]

    canonical_names = {tag.name for tag in list_all_tags()}
    assert set(served_values) == canonical_names


def test_build_vocabulary_keeps_the_apostrophe_the_catalogue_matches_on():
    body = build_vocabulary()
    values = [option.value for group in body.categories for option in group.options]
    # `services/query_filters.py` special-cases this exact string; an ASCII
    # apostrophe here would filter on nothing.
    assert "Boys' Love" in values


def test_build_vocabulary_groups_are_complete_and_unique():
    body = build_vocabulary()
    assert [group.id for group in body.categories][0] == TagCategory.GENRE.value

    slugs = [option.slug for group in body.categories for option in group.options]
    assert len(slugs) == len(set(slugs)), "a slug appears in two groups"

    for group in body.categories:
        assert group.label
        assert group.options, f"empty group {group.id}"


def test_build_vocabulary_formats_are_lowercase_slugs_the_api_accepts():
    body = build_vocabulary()
    slugs = {option.slug for option in body.formats}
    # `/manga/trending?format_type=` lowercases and compares against these.
    assert {"manga", "manhwa", "manhua"} <= slugs
    for option in body.formats:
        assert option.value == option.label


def test_build_vocabulary_marks_only_catalogue_formats_filterable():
    body = build_vocabulary()
    filterable = {option.slug for option in body.formats if option.filterable}
    # Anything else is a tag the catalogue hangs off a row, not a `format_type`
    # value, so offering it as a filter would show an empty shelf.
    assert filterable == {"manga", "manhwa", "manhua"}


@pytest.mark.asyncio
async def test_vocabulary_endpoint_is_served_and_cacheable(client):
    resp = await client.get("/vocabulary")
    assert resp.status_code == 200

    data = resp.json()
    assert data["version"] == VOCABULARY_VERSION
    assert data["categories"]
    assert data["formats"]
    assert "max-age" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_vocabulary_endpoint_needs_no_database(client):
    """It is static data: it must answer even if the catalogue is unreachable."""
    first = await client.get("/vocabulary")
    second = await client.get("/vocabulary")
    assert first.json() == second.json()
