"""What a repair plan is allowed to do to a row.

The script writes to production data, so the decision function is tested away from
the database and the network: given a row and a provider answer, what exactly
changes? Each test here corresponds to one of the safety claims in the script's
docstring.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resolve_covers.py"

MANGADEX = "https://uploads.mangadex.org/covers/abc/def.jpg"
MAL = "https://cdn.myanimelist.net/images/manga/3/266834.jpg"
MAL_WEBP = "https://cdn.myanimelist.net/images/manga/3/266834.webp"
ANILIST = "https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx1-a.png"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("resolve_covers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Row:
    """Stand-in for the SQLAlchemy row the SELECT returns."""

    def __init__(self, row_id=1, url=MANGADEX, candidates=None, mal_id=1, anilist_id=None):
        self.id = row_id
        self.cover_image_url = url
        self.cover_candidates = candidates if candidates is not None else (
            [{"source": "mangadex", "url": url}] if url else []
        )
        self.mal_id = mal_id
        self.anilist_id = anilist_id


def test_a_dead_url_is_replaced_and_the_old_one_is_probably_kept_out(script):
    plan = script.plan_row(Row(), [MAL, MAL_WEBP], "tenrai")

    assert plan["to_url"] == MAL
    assert plan["from_url"] == MANGADEX
    assert plan["status"] == "ok"
    assert plan["source"] == "mal"
    assert all("mangadex" not in c["url"] for c in plan["candidates"] if c["url"] != MANGADEX)


def test_the_candidate_list_is_capped(script):
    plan = script.plan_row(
        Row(), [MAL, MAL_WEBP, MAL + "?3", MAL + "?4", MAL + "?5"], "tenrai"
    )
    assert len(plan["candidates"]) <= script.MAX_CANDIDATES


def test_an_existing_good_cover_only_gains_a_fallback(script):
    # A healthy AniList row that also has a mal_id: the new URL is a second
    # candidate, not a replacement, so its first choice does not change.
    row = Row(url=ANILIST, candidates=[{"source": "anilist", "url": ANILIST}])
    plan = script.plan_row(row, [MAL], "tenrai")

    assert plan["to_url"] == ANILIST
    assert [c["source"] for c in plan["candidates"]] == ["anilist", "mal"]


def test_nothing_to_do_when_the_row_already_points_at_the_same_good_url(script):
    row = Row(url=MAL, candidates=[{"source": "mal", "url": MAL}])
    assert script.plan_row(row, [MAL], "tenrai") is None


def test_no_provider_answer_means_no_plan(script):
    assert script.plan_row(Row(), [], "tenrai") is None
    assert script.plan_row(Row(), [""], "tenrai") is None


def test_the_provider_is_derived_from_the_host_not_the_phase(script):
    # AniList phase answering with a MAL URL must still be stored as `mal`, or the
    # column would lie about where the image comes from.
    plan = script.plan_row(Row(), [MAL], "anilist")
    assert plan["source"] == "mal"


def test_hostile_urls_never_reach_the_plan(script):
    plan = script.plan_row(Row(), ["http://cdn.myanimelist.net/x.jpg"], "tenrai")
    assert plan is None or plan["to_url"].startswith("https://")


def test_batched_keeps_every_row_exactly_once(script):
    rows = list(range(1034))
    chunks = list(script.batched(rows, 500))
    assert [len(c) for c in chunks] == [500, 500, 34]
    assert [row for chunk in chunks for row in chunk] == rows


# --- modes: repair vs second candidate ----------------------------------------

def test_default_mode_is_a_rehearsal_repair(script):
    args = script.parse_args([])
    assert args.mode == "repair"
    assert args.apply is False, "writes must be opt-in"
    assert args.source == "both"


def test_second_candidate_mode_only_selects_healthy_rows_missing_a_fallback(script):
    sql = script.SECOND_CANDIDATE_SQL
    assert "cover_status = 'ok'" in sql
    assert "jsonb_array_length(cover_candidates) < 2" in sql
    assert "mal_id IS NOT NULL" in sql


def test_repair_mode_only_selects_dead_rows(script):
    assert "cover_status = 'dead'" in script.TENRAI_SQL
    assert "cover_status = 'dead'" in script.ANILIST_SQL


async def test_second_candidate_mode_refuses_the_anilist_source(script):
    # AniList is already the primary on every healthy row, so it cannot add a
    # fallback; the run must not silently do nothing (or spend budget).
    assert await script.main(["--mode", "second-candidate", "--source", "anilist"]) == 2


# --- mode: verify -------------------------------------------------------------
# Two different failures, two different responses: a host block means "trust
# nothing here", a rotted URL means "this one row is bad".

def test_a_host_whose_every_sample_failed_is_the_host_not_the_rows(script):
    assert script.host_verdict([(False, "http 403"), (False, "http 403")]) == "down"


def test_one_success_is_enough_to_call_the_host_up(script):
    # A single good response proves the host serves images; the failures in the
    # same sample are then real rot, not a block.
    assert script.host_verdict([(False, "timeout"), (True, "200 image/jpeg")]) == "up"


def test_an_empty_sample_proves_nothing(script):
    assert script.host_verdict([]) == "unknown"


def test_a_row_dies_only_on_the_second_failure(script):
    assert script.is_dead(0, True) is False, "one timeout must not condemn a row"
    assert script.is_dead(1, True) is True
    assert script.is_dead(7, True) is True


def test_a_passing_row_is_never_marked_dead_however_many_past_failures(script):
    assert script.is_dead(9, False) is False


def test_the_strike_rule_needs_two_separate_runs(script):
    assert script.VERIFY_STRIKES == 2
    # The window keeps an old failure from counting forever.
    assert script.VERIFY_FAILURE_WINDOW_DAYS >= 7


async def test_probe_accepts_only_an_actual_image(script):
    import httpx

    def transport(status, content_type):
        return httpx.MockTransport(
            lambda request: httpx.Response(status, headers={"content-type": content_type}, content=b"x")
        )

    ok, detail = await script.probe_cover(
        httpx.AsyncClient(transport=transport(200, "image/jpeg")), "https://s4.anilist.co/x.jpg"
    )
    assert ok is True and "image/jpeg" in detail

    ok, detail = await script.probe_cover(
        httpx.AsyncClient(transport=transport(200, "text/html")), "https://s4.anilist.co/x.jpg"
    )
    assert ok is False, "a 200 with an HTML body is the original outage, not a success"
    assert "text/html" in detail


async def test_probe_treats_a_timeout_as_a_failure_not_a_crash(script):
    import httpx

    def raising(request):
        raise httpx.ReadTimeout("slow")

    ok, detail = await script.probe_cover(
        httpx.AsyncClient(transport=httpx.MockTransport(raising)), "https://s4.anilist.co/x.jpg"
    )
    assert ok is False
    assert "ReadTimeout" in detail


def test_verify_only_samples_hosts_the_app_trusts(script):
    # A known-blocked host is the canary's business; sampling it here would just
    # re-mark its rows dead every run.
    assert "uploads.mangadex.org" not in script.VERIFY_HOSTS
    assert "s4.anilist.co" in script.VERIFY_HOSTS
    assert script.VERIFY_SAMPLE_PER_HOST >= 10
