"""SVC-04: LLM reasoning is decoration — it must never fail a request.

Each test pins one of the three defects the Stage 8 probe reproduced: a NULL
synopsis aborting the whole batch, a prompt that asks for an array while Groq's
`json_object` mode only returns an object, and string ids that never match the
int primary keys the router looks up.
"""

import json
from types import SimpleNamespace

from app.services import llm


class _Manga:
    def __init__(self, id, synopsis=None, tags=None):
        self.id = id
        self.synopsis = synopsis
        self.title_english = f"Title {id}"
        self.title_romaji = None
        self.genres = ["Action"]
        self.tags = tags if tags is not None else [{"name": "Survival"}]


class _Completions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _install(monkeypatch, payload):
    """Point the module at a fake Groq client and return the recorded calls."""
    completions = _Completions(json.dumps(payload) if not isinstance(payload, str) else payload)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm, "client", client)
    return completions


async def test_null_synopsis_does_not_abort_the_batch(monkeypatch):
    """The old code did `m.synopsis[:200]` outside the try and raised out of
    `/recommend`, so one catalogue row without a synopsis failed the request."""
    comp = _install(monkeypatch, {"results": [{"id": 1, "reasoning": "fits"}]})
    candidates = [
        {"manga": _Manga(1, synopsis=None)},
        {"manga": _Manga(2, synopsis="A real synopsis.")},
    ]

    reasoning = await llm.generate_reasoning("dark fantasy", candidates)

    assert reasoning == {1: "fits"}
    prompt = comp.calls[0]["messages"][1]["content"]
    assert "id=1" in prompt and "id=2" in prompt
    assert llm.NO_SYNOPSIS in prompt
    assert "A real synopsis." in prompt


async def test_prompt_and_response_format_describe_the_same_shape(monkeypatch):
    """Groq's json_object mode rejects an array, so the prompt must ask for an object."""
    assert '"results"' in llm.SYSTEM_PROMPT
    comp = _install(monkeypatch, {"results": []})

    await llm.generate_reasoning("q", [{"manga": _Manga(1, synopsis="s")}])

    assert comp.calls[0]["response_format"] == {"type": "json_object"}


async def test_string_ids_are_normalised_to_int(monkeypatch):
    """The router looks up `reasoning_map.get(m.id)`, and `m.id` is an int."""
    _install(monkeypatch, {"results": [{"id": "12", "reasoning": "fits"}]})

    reasoning = await llm.generate_reasoning(
        "q", [{"manga": _Manga(12, synopsis="s")}]
    )

    assert reasoning == {12: "fits"}
    assert reasoning.get(12) == "fits"


async def test_malformed_entries_are_skipped_but_valid_ones_survive(monkeypatch):
    _install(
        monkeypatch,
        {
            "results": [
                {"id": "2", "reasoning": "  keep me  "},
                {"id": "not-an-id", "reasoning": "drop"},
                "junk",
                {"id": None, "reasoning": "drop"},
                {"id": 3, "reasoning": None},
                {"id": 4},
            ]
        },
    )

    reasoning = await llm.generate_reasoning(
        "q", [{"manga": _Manga(2, synopsis="s")}]
    )

    assert reasoning == {2: "keep me"}


async def test_bare_list_payload_is_still_accepted(monkeypatch):
    """Tolerance, not the contract: an older model may answer with the array the
    old prompt asked for."""
    _install(monkeypatch, [{"id": "5", "reasoning": "list shape"}])

    reasoning = await llm.generate_reasoning("q", [{"manga": _Manga(5, synopsis="s")}])

    assert reasoning == {5: "list shape"}


async def test_malformed_json_returns_empty_instead_of_raising(monkeypatch):
    _install(monkeypatch, "not json at all")

    assert await llm.generate_reasoning("q", [{"manga": _Manga(1, synopsis="s")}]) == {}


async def test_candidate_without_manga_is_skipped(monkeypatch):
    comp = _install(monkeypatch, {"results": []})

    await llm.generate_reasoning("q", [{"not_manga": _Manga(1)}])

    assert comp.calls == []


async def test_no_client_returns_empty_without_calling(monkeypatch):
    monkeypatch.setattr(llm, "client", None)

    assert await llm.generate_reasoning("q", [{"manga": _Manga(1)}]) == {}


async def test_empty_candidates_does_not_call_the_model(monkeypatch):
    comp = _install(monkeypatch, {"results": []})

    assert await llm.generate_reasoning("q", []) == {}
    assert comp.calls == []
