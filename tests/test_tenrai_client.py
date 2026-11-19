"""Behaviour of the Tenrai cover client, exercised against a fake transport.

The live API has three properties that broke naive implementations, and these
tests pin each one:

* a batch can answer fewer entries than requested (MAL ids 5 and 6 do not exist),
  so entries must be keyed by the returned `mal_id` rather than by position;
* ids come back in whatever order the service likes;
* one chunk can fail without the rest being thrown away.
"""

import httpx
import pytest

from app.ingestion.tenrai_client import (
    TENRAI_API_URL,
    chunks,
    fetch_covers,
    fetch_entries,
    pick_cover_urls,
)


def entry(mal_id: int, jpg: str = None, webp: str = None, large: str = None) -> dict:
    return {
        "mal_id": mal_id,
        "title": f"Title {mal_id}",
        "images": {
            "jpg": {
                "image_url": jpg or f"https://cdn.myanimelist.net/images/manga/{mal_id}.jpg",
                "large_image_url": large,
                "small_image_url": None,
            },
            "webp": {"image_url": webp},
        },
    }


def transport_for(handler):
    return httpx.MockTransport(handler)


def batcher(payloads, seen=None):
    """Answer each request by slicing `payloads` in the order requests arrive."""

    def handler(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["ids"].split(",")]
        if seen is not None:
            seen.append((ids, request.url.params.get("limit")))
        data = [item for item in payloads if item["mal_id"] in ids]
        return httpx.Response(200, json={"pagination": {}, "data": data})

    return handler


def test_chunks_slices_without_losing_the_tail():
    assert list(chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunks([], 50)) == []


def test_pick_cover_urls_prefers_the_card_sized_jpg_and_deduplicates():
    urls = pick_cover_urls(
        entry(
            1,
            jpg="https://cdn.myanimelist.net/a.jpg",
            webp="https://cdn.myanimelist.net/a.webp",
            large="https://cdn.myanimelist.net/a_l.jpg",
        )
    )
    assert urls == [
        "https://cdn.myanimelist.net/a.jpg",
        "https://cdn.myanimelist.net/a.webp",
        "https://cdn.myanimelist.net/a_l.jpg",
    ]


def test_pick_cover_urls_drops_hosts_and_schemes_outside_the_allowlist():
    urls = pick_cover_urls(
        entry(
            1,
            jpg="https://evil.example/a.jpg",
            webp="http://cdn.myanimelist.net/a.webp",
            large="https://cdn.myanimelist.net/a_l.jpg",
        )
    )
    assert urls == ["https://cdn.myanimelist.net/a_l.jpg"]


def test_pick_cover_urls_tolerates_a_missing_images_block():
    assert pick_cover_urls({"mal_id": 1}) == []
    assert pick_cover_urls({"mal_id": 1, "images": None}) == []


async def test_entries_are_keyed_by_the_returned_id_not_by_position():
    # Requested in ascending order, answered in reverse: a positional pairing
    # would attach cover 3 to title 1.
    payloads = [entry(3), entry(2), entry(1)]
    seen = []
    found = await fetch_entries([1, 2, 3], transport=transport_for(batcher(payloads, seen)))

    assert sorted(found) == [1, 2, 3]
    assert found[1]["title"] == "Title 1"
    assert found[3]["title"] == "Title 3"
    assert seen[0][0] == [1, 2, 3]


async def test_ids_the_service_does_not_know_are_absent_not_shifted():
    payloads = [entry(1), entry(2), entry(4)]
    found = await fetch_entries([1, 2, 3, 4], transport=transport_for(batcher(payloads)))
    assert sorted(found) == [1, 2, 4]
    assert 3 not in found


async def test_an_id_that_was_not_requested_is_dropped():
    payloads = [entry(1), entry(999)]
    found = await fetch_entries([1], transport=transport_for(batcher(payloads)))
    assert list(found) == [1]


async def test_ids_are_split_into_batches_of_fifty():
    ids = list(range(1, 121))
    seen = []
    found = await fetch_entries(ids, transport=transport_for(batcher([entry(i) for i in ids], seen)))

    assert len(found) == 120
    assert len(seen) == 3
    assert [len(batch) for batch, _limit in seen] == [50, 50, 20]
    assert all(limit == str(len(batch)) for batch, limit in seen)


async def test_one_failed_chunk_does_not_discard_the_others():
    ids = list(range(1, 121))
    payloads = [entry(i) for i in ids]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, json={"detail": "upstream down"})
        requested = [int(i) for i in request.url.params["ids"].split(",")]
        return httpx.Response(200, json={"data": [e for e in payloads if e["mal_id"] in requested]})

    found = await fetch_entries(ids, transport=transport_for(handler))

    # The first 50 are lost, the remaining 70 survive.
    assert sorted(found) == list(range(51, 121))


async def test_a_response_without_a_data_list_is_skipped():
    def handler(request):
        return httpx.Response(200, json={"pagination": {}})

    assert await fetch_entries([1], transport=transport_for(handler)) == {}


async def test_no_ids_makes_no_request():
    def handler(request):  # pragma: no cover - must never run
        raise AssertionError("no request expected")

    assert await fetch_entries([], transport=transport_for(handler)) == {}
    assert await fetch_covers([], transport=transport_for(handler)) == {}


async def test_fetch_covers_only_returns_ids_with_an_usable_cover():
    no_cover = {"mal_id": 2, "title": "No image", "images": {"jpg": {"image_url": "https://evil.example/x.jpg"}}}
    payloads = [entry(1), no_cover]

    covers = await fetch_covers([1, 2], transport=transport_for(batcher(payloads)))

    assert list(covers) == [1]
    assert covers[1][0] == "https://cdn.myanimelist.net/images/manga/1.jpg"


def test_requests_go_to_the_versioned_endpoint():
    # /manga answers 301 to /v1/manga; calling the versioned path avoids a redirect
    # on every batch.
    assert TENRAI_API_URL.endswith("/v1/manga")


# --- pacing: timeout and delay are configuration, so they are asserted ---------

async def test_every_request_carries_the_configured_timeout():
    from app.ingestion import tenrai_client

    seen_timeouts = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout"))
        requested = [int(i) for i in request.url.params["ids"].split(",")]
        return httpx.Response(200, json={"data": [entry(i) for i in requested]})

    await fetch_entries([1, 2], transport=transport_for(handler))

    assert seen_timeouts, "the request never reached the transport"
    assert seen_timeouts[0]["read"] == pytest.approx(20.0)
    assert seen_timeouts[0]["connect"] == pytest.approx(8.0)


async def test_client_is_built_with_the_shared_timeout_object(monkeypatch):
    from app.ingestion import tenrai_client

    captured = {}
    real_client = httpx.AsyncClient

    class SpyClient(real_client):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(tenrai_client.httpx, "AsyncClient", SpyClient)
    await fetch_entries([1], transport=transport_for(batcher([entry(1)])))

    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["headers"]["User-Agent"] == tenrai_client.USER_AGENT


async def test_a_gap_is_kept_between_batches():
    import time as _time
    from app.ingestion import tenrai_client

    ids = list(range(1, 60))  # two batches
    stamps = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(_time.monotonic())
        requested = [int(i) for i in request.url.params["ids"].split(",")]
        return httpx.Response(200, json={"data": [entry(i) for i in requested]})

    await fetch_entries(ids, transport=transport_for(handler))

    assert len(stamps) == 2
    # Bucket pacing (1.5 rps) plus the explicit inter-batch gap.
    assert stamps[1] - stamps[0] >= tenrai_client.TENRAI_BATCH_GAP_SECONDS


async def test_a_failing_batch_is_retried_only_the_configured_number_of_times():
    from app.ingestion import tenrai_client

    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"})

    # A 429 is retried, so it exhausts the ceiling rather than being treated as a
    # dead chunk. The configured limit is what the client passes to the limiter, so
    # this fails if anyone quietly restores the 6-attempt default.
    found = await fetch_entries([1], transport=transport_for(handler))

    assert found == {}
    assert len(attempts) == tenrai_client.TENRAI_MAX_RETRIES
    assert tenrai_client.TENRAI_MAX_RETRIES < 6
