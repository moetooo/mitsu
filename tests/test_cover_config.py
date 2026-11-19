"""Cover policy comes from configuration, not from a tuple in a module.

The MangaDex block cost 10,463 covers and then cost *another* deploy to notice it
was over: reinstating a host was a code change. These tests pin the arrangement
that replaced it - config values win, unusable values fall back, and nothing is
silently accepted.
"""

import pytest

from app.config import settings
from app.core import covers


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def cover_settings(monkeypatch):
    """Set cover settings per test, and restore them afterwards."""

    def apply(**values):
        for name, value in values.items():
            monkeypatch.setattr(settings, name, value, raising=False)

    yield apply


def test_the_defaults_are_the_policy_the_catalogue_was_built_for():
    assert "s4.anilist.co" in covers.allowed_hosts()
    assert "uploads.mangadex.org" in covers.blocked_hosts()
    assert covers.source_order()[0] == "anilist"
    assert covers.max_candidates() == 3
    assert covers.validate_cover_config() == []


def test_a_host_can_be_reinstated_without_a_code_change(cover_settings):
    # The whole point: the canary says the block lifted, an operator changes one
    # variable, and the host is usable again.
    cover_settings(COVER_BLOCKED_HOSTS="", COVER_ALLOWED_HOSTS="s4.anilist.co,uploads.mangadex.org")

    url = "https://uploads.mangadex.org/covers/x/y.png"
    assert covers.is_blocked(url) is False
    assert covers.is_browser_safe(url) is True
    assert covers.classify_cover(url) == ("ok", "mangadex")


def test_a_host_can_be_banned_without_a_code_change(cover_settings):
    cover_settings(COVER_ALLOWED_HOSTS="cdn.myanimelist.net")

    assert covers.is_browser_safe("https://s4.anilist.co/x.jpg") is False
    assert covers.classify_cover("https://s4.anilist.co/x.jpg") == ("unverified", "anilist")


def test_the_provider_order_is_configuration(cover_settings):
    titles = [
        {"url": "https://s4.anilist.co/a.jpg", "source": "anilist"},
        {"url": "https://cdn.myanimelist.net/a.jpg", "source": "mal"},
    ]

    anilist_first = covers.merge_candidates(titles, [])
    cover_settings(COVER_SOURCE_ORDER="mal,anilist")
    mal_first = covers.merge_candidates(titles, [])

    assert anilist_first[0]["source"] == "anilist"
    assert mal_first[0]["source"] == "mal"
    assert covers.primary_url(mal_first) == "https://cdn.myanimelist.net/a.jpg"


def test_the_candidate_cap_is_configuration_and_is_clamped(cover_settings):
    titles = [
        {"url": "https://s4.anilist.co/a.jpg", "source": "anilist"},
        {"url": "https://cdn.myanimelist.net/a.jpg", "source": "mal"},
        {"url": "https://media.kitsu.app/a.jpg", "source": "kitsu"},
    ]

    cover_settings(COVER_MAX_CANDIDATES=1)
    assert len(covers.merge_candidates(titles, [])) == 1

    cover_settings(COVER_MAX_CANDIDATES=99)
    assert covers.max_candidates() == 5, "an absurd cap must not become an unbounded list"

    cover_settings(COVER_MAX_CANDIDATES="not a number")
    assert covers.max_candidates() == 3, "a typo falls back to the default"


def test_a_provider_name_the_database_rejects_is_reported(cover_settings):
    # `ck_manga_cover_source` accepts anilist|mal|kitsu|mangadex only, so an unknown
    # name would fail at INSERT time - it has to be caught at startup instead.
    cover_settings(COVER_SOURCE_ORDER="anilist,jikan")

    problems = covers.validate_cover_config()
    assert any("jikan" in problem for problem in problems)
    assert "jikan" not in covers.source_order()


def test_a_host_in_both_lists_is_treated_as_blocked(cover_settings):
    cover_settings(
        COVER_ALLOWED_HOSTS="s4.anilist.co,uploads.mangadex.org",
        COVER_BLOCKED_HOSTS="uploads.mangadex.org",
    )

    assert covers.is_browser_safe("https://uploads.mangadex.org/covers/x/y.png") is False
    assert any("both" in problem for problem in covers.validate_cover_config())


@pytest.mark.parametrize(
    "value",
    ["s4.anilist.co/", "ht!tp://x", "s4.anilist.co/covers"],
)
def test_a_value_that_is_not_a_hostname_is_reported(cover_settings, value):
    cover_settings(COVER_ALLOWED_HOSTS=value)
    assert any("hostname" in problem for problem in covers.validate_cover_config())


def test_an_empty_allowlist_is_reported_rather_than_silently_used(cover_settings):
    cover_settings(COVER_ALLOWED_HOSTS="")
    problems = covers.validate_cover_config()
    assert any("COVER_ALLOWED_HOSTS is empty" in problem for problem in problems)
    # Falls back to the defaults instead of making every cover unusable.
    assert covers.allowed_hosts() == covers.BROWSER_SAFE_HOSTS


def test_a_blocked_host_never_becomes_a_candidate(cover_settings):
    cover_settings(COVER_BLOCKED_HOSTS="cdn.myanimelist.net", COVER_ALLOWED_HOSTS="s4.anilist.co")

    assert covers.make_candidate("https://cdn.myanimelist.net/a.jpg") is None
    url, entries = covers.public_cover("https://cdn.myanimelist.net/a.jpg", [])
    assert (url, entries) == (None, [])


def test_health_reports_the_live_policy():
    from app.services.cover_health import _policy

    policy = _policy()
    assert policy["allowed_hosts"] and policy["source_order"]
    assert policy["problems"] == []


async def test_a_cached_health_answer_still_reports_the_current_policy(client, cover_settings):
    first = (await client.get("/health/covers")).json()
    assert first["policy"]["source_order"][0] == "anilist"

    cover_settings(COVER_SOURCE_ORDER="mal,anilist")
    second = (await client.get("/health/covers")).json()

    assert second["checked_at"] == first["checked_at"], "counters should still be cached"
    assert second["policy"]["source_order"][0] == "mal", "the policy must not be served stale"
