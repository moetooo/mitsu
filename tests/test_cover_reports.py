"""`POST /covers/{id}/broken` - the reader's report, and what it may not do.

The endpoint is anonymous, so the tests care as much about what it refuses (no
status changes, no rows for unknown ids, one row per day) as about what it
records.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.main import app
from app.services import cover_reports
from tests.conftest import FILE_COVER_URL, FILE_MANGA_ID


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _reports(manga_id: int):
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text(
                    "SELECT from_url, source, detail FROM cover_repair_log "
                    "WHERE manga_id = :i AND result = 'reported'"
                ),
                {"i": manga_id},
            )
        ).all()


async def test_a_report_is_accepted_and_recorded(client, manga_id):
    response = await client.post(f"/covers/{manga_id}/broken", json={"reason": "broken_image"})

    assert response.status_code == 202
    body = response.json()
    assert body["recorded"] is True
    assert body["manga_id"] == manga_id

    rows = await _reports(manga_id)
    assert len(rows) == 1
    assert rows[0].detail == "broken_image"
    assert rows[0].from_url, "the log must keep the URL that was reported"


async def test_a_report_never_changes_the_cover_status(client, manga_id):
    async with AsyncSessionLocal() as session:
        before = (
            await session.execute(text("SELECT cover_status FROM manga WHERE id = :i"), {"i": manga_id})
        ).scalar()

    await client.post(f"/covers/{manga_id}/broken", json={"reason": "all_candidates_failed"})

    async with AsyncSessionLocal() as session:
        after = (
            await session.execute(text("SELECT cover_status FROM manga WHERE id = :i"), {"i": manga_id})
        ).scalar()

    assert after == before, "an anonymous report must not take a cover off a card"


async def test_one_report_per_day_per_title(client, manga_id):
    first = await client.post(f"/covers/{manga_id}/broken", json={"reason": "broken_image"})
    second = await client.post(f"/covers/{manga_id}/broken", json={"reason": "broken_image"})

    assert first.json()["recorded"] is True
    assert second.status_code == 202
    assert second.json()["recorded"] is False
    assert "already reported" in second.json()["message"]
    assert len(await _reports(manga_id)) == 1


async def test_an_unknown_id_is_a_404_and_writes_nothing(client):
    response = await client.post("/covers/999999999/broken", json={"reason": "broken_image"})

    assert response.status_code == 404
    async with AsyncSessionLocal() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM cover_repair_log WHERE manga_id = 999999999")
            )
        ).scalar()
    assert count == 0


async def test_a_free_text_reason_is_rejected(client, manga_id):
    # An enum in the model is what keeps anonymous input out of the log body.
    response = await client.post(f"/covers/{manga_id}/broken", json={"reason": "DROP TABLE"})
    assert response.status_code == 422


async def test_a_bodyless_post_still_works(client, manga_id):
    # The browser sends it from an image error handler, where there is no budget
    # for building a payload.
    response = await client.post(f"/covers/{manga_id}/broken")

    assert response.status_code == 202
    assert response.json()["recorded"] is True
    assert (await _reports(manga_id))[0].detail == "all_candidates_failed"


async def test_the_verify_queue_lists_reported_titles(manga_id):
    async with AsyncSessionLocal() as session:
        await cover_reports.record_broken_report(session, manga_id, reason="broken_image")
        ids = await cover_reports.reported_ids(session, limit=50)

    assert manga_id in ids


async def test_an_unknown_reason_falls_back_instead_of_being_stored(manga_id):
    async with AsyncSessionLocal() as session:
        await cover_reports.record_broken_report(session, manga_id, reason="whatever this is")
        detail = await _reports(manga_id)

    assert detail[0].detail == cover_reports.DEFAULT_REASON
