import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

# -------------------------------------------------------------
# 1. Health & Search API Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_health(client):
    """GET /health reports the API and every dependency it needs."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["services"]["database"]["status"] == "connected"
    assert data["services"]["redis"]["status"] == "connected"

@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_search_title(client):
    """GET /search?q=berserk must return matches containing Berserk."""
    resp = await client.get("/search?q=berserk")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert any(
        "berserk" in (item.get("title_english") or item.get("title_romaji") or "").lower()
        for item in data
    )

# -------------------------------------------------------------
# 2. Trending API with Format & Genre Tests
# -------------------------------------------------------------
@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_trending_manga_only(client):
    """GET /manga/trending?format_type=manga must return trending items."""
    resp = await client.get("/manga/trending?format_type=manga&page=1&limit=8")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    # Every returned item has format_type or title
    for item in data:
        assert item.get("title") is not None
        if item.get("format_type"):
            assert item.get("format_type") == "MANGA"

@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_trending_with_genre(client):
    """GET /manga/trending?genre=Action must return trending items filtered by Action."""
    resp = await client.get("/manga/trending?genre=Action&page=1&limit=8")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

# -------------------------------------------------------------
# 3. Roulette & Roulette Batch API Tests
# -------------------------------------------------------------
@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_roulette_single_manga_only(client):
    """POST /roulette with format_type=['manga'] must return a single candidate with format_type MANGA."""
    payload = {
        "filters": {"format_type": ["manga"]}
    }
    resp = await client.post("/roulette", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data.get("format_type") == "MANGA"
    title = data.get("title") or ""
    assert len(title) > 0

@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_roulette_batch_manga_only(client):
    """POST /roulette/batch with format_type=['manga'] must return candidates that are all MANGA."""
    payload = {
        "filters": {"format_type": ["manga"]},
        "count": 6
    }
    resp = await client.post("/roulette/batch", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

    for item in data:
        assert item.get("format_type") == "MANGA"
        title = item.get("title") or ""
        genres = [g.lower() for g in (item.get("genres") or [])]
        assert "manhwa" not in genres
        assert "manhua" not in genres

@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_roulette_batch_manhwa_only(client):
    """POST /roulette/batch with format_type=['manhwa'] must return candidates that are all MANHWA."""
    payload = {
        "filters": {"format_type": ["manhwa"]},
        "count": 6
    }
    resp = await client.post("/roulette/batch", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

    for item in data:
        assert item.get("format_type") == "MANHWA"

# -------------------------------------------------------------
# 4. Recommendations API with Filters Test
# -------------------------------------------------------------
@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_api_recommend_manga_only(client):
    """POST /recommend with format_type=['manga'] must return recommendations where format_type is MANGA."""
    payload = {
        "query": "superpower hero academy",
        "filters": {"format_type": ["manga"]},
        "limit": 6
    }
    resp = await client.post("/recommend", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    results = data.get("results", [])
    assert len(results) > 0

    for r in results:
        assert r.get("format_type") == "MANGA"
        title = r.get("title") or ""
        genres = [g.lower() for g in (r.get("genres") or [])]
        assert "manhwa" not in genres
        assert "manhua" not in genres
