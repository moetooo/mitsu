"""Admin surface tests.

The admin surface is fail-closed: with no token and no password login
configured every guarded route answers 503, and with either one configured a
signed-out caller gets 401. These tests assert that intent rather than the old
open-access behaviour.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_sync_status_requires_auth(client, admin_headers):
    assert (await client.get("/admin/sync/status")).status_code == 401

    response = await client.get("/admin/sync/status", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "enabled" in data
    assert isinstance(data["runs"], list)


@pytest.mark.asyncio
async def test_admin_fails_closed_without_any_credentials(client, monkeypatch):
    """No token and no password login means 503, never anonymous access."""
    monkeypatch.setattr(settings, "SYNC_ADMIN_TOKEN", "")
    monkeypatch.setattr(settings, "SYNC_ADMIN_USERNAME", "")
    monkeypatch.setattr(settings, "SYNC_ADMIN_PASSWORD", "")

    for path in ("/admin/sync/status", "/admin/ingestion-status", "/admin/sync/health"):
        response = await client.get(path)
        assert response.status_code == 503, path
        assert "not configured" in response.json()["detail"]

    # Mutations must be closed as well, not just reads.
    assert (await client.post("/admin/sync")).status_code == 503
    assert (await client.post("/admin/auto?enabled=true")).status_code == 503


@pytest.mark.asyncio
async def test_ingestion_status_requires_auth(client, admin_headers):
    assert (await client.get("/admin/ingestion-status")).status_code == 401
    response = await client.get("/admin/ingestion-status", headers=admin_headers)
    assert response.status_code == 200
    assert "total_manga_in_db" in response.json()


@pytest.mark.asyncio
async def test_sync_admin_token_is_enforced(client, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_ADMIN_TOKEN", "test-secret")
    assert (await client.get("/admin/sync/status")).status_code == 401

    response = await client.get(
        "/admin/sync/status",
        headers={"X-Admin-Token": "test-secret"},
    )
    assert response.status_code == 200


@pytest.mark.requires_dashboard
@pytest.mark.asyncio
async def test_dashboard_serves_login_shell(client, admin_headers):
    """The shell renders signed out, but the admin surface still reports closed."""
    signed_out = await client.get("/admin/dashboard")
    # The shell may report 200 or 401 while signed out; either way it renders
    # the login form and contains no credentials.
    assert signed_out.status_code in {200, 401}
    # The shell itself carries no data, but it must still render so the login
    # form is reachable.
    assert "<div id=\"root\">" in signed_out.text or "Catalog control" in signed_out.text
    assert signed_out.headers.get("cache-control") == "no-store"
    assert "__SYNC_ADMIN_TOKEN__" not in signed_out.text

    signed_in = await client.get("/admin/dashboard", headers=admin_headers)
    assert signed_in.status_code == 200


@pytest.mark.asyncio
async def test_api_root_is_not_a_page(client):
    assert (await client.get("/")).status_code == 404
    assert (await client.get("/api/dashboard")).status_code == 404


@pytest.mark.asyncio
async def test_password_login_sets_session_and_unlocks_status(client, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "SYNC_ADMIN_PASSWORD", "correct horse!@#42")
    monkeypatch.setattr(settings, "SYNC_ADMIN_SESSION_SECRET", "test-session-secret")

    assert (await client.get("/admin/sync/status")).status_code == 401

    bad = await client.post(
        "/admin/login", json={"username": "admin", "password": "wrong"}
    )
    assert bad.status_code == 401

    good = await client.post(
        "/admin/login", json={"username": "admin", "password": "correct horse!@#42"}
    )
    assert good.status_code == 200
    assert good.json()["authenticated"] is True
    assert "mitsu_admin_session" in good.cookies

    status = await client.get("/admin/sync/status")
    assert status.status_code == 200

    session = await client.get("/admin/session")
    assert session.json()["authenticated"] is True
    assert session.json()["username"] == "admin"
    assert session.json()["auth_required"] is True

    logged_out = await client.post("/admin/logout")
    assert logged_out.status_code == 200
    assert (await client.get("/admin/sync/status")).status_code == 401


@pytest.mark.asyncio
async def test_repeated_bad_logins_are_rate_limited(client, monkeypatch):
    from app.routers.admin import _LOGIN_FAILURES

    monkeypatch.setattr(settings, "SYNC_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "SYNC_ADMIN_PASSWORD", "correct horse!@#42")
    monkeypatch.setattr(settings, "SYNC_ADMIN_SESSION_SECRET", "test-session-secret")
    _LOGIN_FAILURES.clear()
    try:
        for _ in range(5):
            response = await client.post(
                "/admin/login", json={"username": "admin", "password": "wrong"}
            )
            assert response.status_code == 401
        blocked = await client.post(
            "/admin/login", json={"username": "admin", "password": "correct horse!@#42"}
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
    finally:
        _LOGIN_FAILURES.clear()


@pytest.mark.asyncio
async def test_session_reports_required_auth_without_password_login(client, monkeypatch):
    """A token-only deployment still reports auth as required and login disabled."""
    monkeypatch.setattr(settings, "SYNC_ADMIN_USERNAME", "")
    monkeypatch.setattr(settings, "SYNC_ADMIN_PASSWORD", "")

    session = await client.get("/admin/session")
    assert session.status_code == 200
    body = session.json()
    assert body["authenticated"] is False
    assert body["auth_required"] is True
    assert body["login_enabled"] is False


@pytest.mark.asyncio
async def test_login_is_rejected_when_password_login_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_ADMIN_TOKEN", "api-only-token")
    response = await client.post(
        "/admin/login", json={"username": "admin", "password": "anything"}
    )
    assert response.status_code == 503
