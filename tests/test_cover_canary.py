"""The MangaDex cover canary: verdicts, the weekly lock, and the loop.

Every test injects an `httpx.MockTransport`, so nothing here touches the network.
The verdict table is the important part: the original outage was `200 OK` with an
HTML body, and a canary that treats any 200 as success is worse than no canary.
"""

import asyncio
import uuid

import httpx
import pytest

from app.services import cover_canary

URL = "https://uploads.mangadex.org/covers/test/test.png"


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch):
    """A fresh Redis namespace per test.

    The real keys live for a week, so a test that reused them would find the lock
    already held and silently skip every probe after the first.
    """
    namespace = f"test:cover:canary:{uuid.uuid4().hex}"
    monkeypatch.setattr(cover_canary, "LOCK_KEY", f"{namespace}:due")
    monkeypatch.setattr(cover_canary, "STATE_KEY", f"{namespace}:state")
    monkeypatch.setattr(cover_canary, "_last_probe_at", None)
    return monkeypatch


def transport_returning(status=200, content_type="image/png", body=b"x"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": content_type}, content=body)

    return httpx.MockTransport(handler)


def transport_raising(exc):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.MockTransport(handler)


async def test_image_response_means_the_block_has_lifted():
    result = await cover_canary.probe(URL, transport=transport_returning(200, "image/jpeg"))

    assert result["verdict"] == "ok"
    assert result["status"] == 200
    assert result["content_type"] == "image/jpeg"


async def test_a_200_with_an_html_body_is_the_block_not_a_success():
    # This is the exact shape of the original outage: the status line lied.
    result = await cover_canary.probe(URL, transport=transport_returning(200, "text/html"))

    assert result["verdict"] == "blocked"
    assert result["status"] == 200


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_blocking_statuses_are_reported_as_blocked(status):
    result = await cover_canary.probe(URL, transport=transport_returning(status, "text/html"))
    assert result["verdict"] == "blocked"


async def test_a_server_error_is_inconclusive_rather_than_a_verdict():
    result = await cover_canary.probe(URL, transport=transport_returning(500, "text/plain"))
    assert result["verdict"] == "error"


async def test_a_timeout_is_inconclusive_and_does_not_raise():
    result = await cover_canary.probe(
        URL, transport=transport_raising(httpx.ConnectTimeout("slow host"))
    )

    assert result["verdict"] == "error"
    assert "ConnectTimeout" in result["detail"]


async def test_one_probe_per_week_is_enforced_by_the_redis_lock():
    transport = transport_returning(200, "image/png")

    first = await cover_canary.run_canary(url=URL, transport=transport)
    second = await cover_canary.run_canary(url=URL, transport=transport)

    assert first["verdict"] == "ok"
    assert second == {"skipped": True, "reason": "checked within the last week"}


async def test_force_overrides_the_weekly_lock():
    transport = transport_returning(200, "image/png")
    await cover_canary.run_canary(url=URL, transport=transport)

    forced = await cover_canary.run_canary(force=True, url=URL, transport=transport)

    assert forced["verdict"] == "ok"
    assert not forced.get("skipped")


async def test_the_verdict_is_recorded_for_health_reporting():
    await cover_canary.run_canary(url=URL, transport=transport_returning(200, "text/html"))

    state = await cover_canary.last_state()

    assert state is not None
    assert state["verdict"] == "blocked"
    assert state["content_type"] == "text/html"


async def test_redis_outage_falls_back_to_an_in_process_throttle(isolated_keys):
    async def broken_set(*args, **kwargs):
        raise ConnectionError("redis down")

    isolated_keys.setattr(cover_canary.redis_client, "set", broken_set)

    first = await cover_canary.run_canary(url=URL, transport=transport_returning(200, "image/png"))
    second = await cover_canary.run_canary(url=URL, transport=transport_returning(200, "image/png"))

    assert first["verdict"] == "ok"
    assert second["skipped"] is True


async def test_the_loop_probes_and_stops_when_asked():
    probes = []

    def handler(request):
        probes.append(request.url)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x")

    stop = asyncio.Event()
    task = asyncio.create_task(
        cover_canary.canary_loop(stop, check_interval=0.01, transport=httpx.MockTransport(handler))
    )

    for _ in range(50):
        await asyncio.sleep(0.01)
        if probes:
            break

    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert probes, "the loop never probed"
    assert task.done()


async def test_the_canary_never_raises_out_of_the_loop():
    # A transport that explodes must be swallowed: a monitoring probe is not
    # allowed to take the application down.
    stop = asyncio.Event()
    task = asyncio.create_task(
        cover_canary.canary_loop(
            stop, check_interval=0.01, transport=transport_raising(RuntimeError("boom"))
        )
    )
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert task.done()


def test_probe_headers_look_like_a_browser():
    # Without browser headers the probe measures a different endpoint than users
    # hit, which is how the original block was misjudged.
    assert "Mozilla" in cover_canary.BROWSER_HEADERS["User-Agent"]
    assert cover_canary.BROWSER_HEADERS["Accept"].startswith("image/")


def test_the_probe_url_is_a_real_cover_path():
    assert cover_canary.CANARY_URL.startswith("https://uploads.mangadex.org/covers/")
    assert cover_canary.CANARY_URL.endswith(".png")
