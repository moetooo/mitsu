"""Reasoning for /recommend results — a decoration, never a failure.

Three rules, each of which used to be broken (SVC-04):

1. **No candidate may break the batch.** The prompt is built with ``.get`` and a
   ``None`` synopsis becomes a placeholder instead of a ``TypeError``.
2. **The prompt and ``response_format`` describe the same shape.** Groq's
   ``json_object`` mode only accepts an object, so the prompt asks for
   ``{"results": [...]}``; the parser still tolerates a bare list.
3. **Ids come back as ints.** The model returns ``"12"`` while callers look up
   ``reasoning_map.get(12)``; the map is normalised to ``int`` so the reasoning
   actually reaches the response. Unknown/malformed entries are skipped, and
   nothing in here raises: ``/recommend`` must answer without reasoning rather
   than fail.
"""

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from groq import AsyncGroq

from ..config import settings

logger = logging.getLogger("mitsu.llm")

client = AsyncGroq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

# One report per (model, failure) per process. A wrong model id used to print the
# provider's full error dict on every single request; the first line is the one
# that helps, the next thousand are noise.
_reported_failures: set = set()


def _compact(error: Exception) -> str:
    """One line, bounded: a provider error body is multi-line and unbounded."""
    return " ".join(str(error).split())[:160]


def _report_failure(error: Exception) -> None:
    status = getattr(error, "status_code", None) or type(error).__name__
    key = f"{settings.LLM_REASONING_MODEL}|{status}"
    if key in _reported_failures:
        logger.debug("LLM reasoning failed again (model=%s status=%s)", settings.LLM_REASONING_MODEL, status)
        return
    _reported_failures.add(key)
    logger.warning(
        "LLM reasoning unavailable, results are served without it: model=%s status=%s detail=%s",
        settings.LLM_REASONING_MODEL,
        status,
        _compact(error),
    )

MAX_SYNOPSIS_CHARS = 200
NO_SYNOPSIS = "(no synopsis)"

SYSTEM_PROMPT = """You are a manga recommendation assistant. You will be given a user's request
and a list of candidate manga (title, synopsis, genres, tags). For each
candidate, write ONE sentence explaining specifically why it matches the
user's request, referencing concrete plot/tone elements — not generic praise.
Return ONLY valid JSON, no markdown formatting, in this exact shape:
{"results": [{"id": <id>, "reasoning": "<one sentence>"}]}
"""


def _synopsis_excerpt(synopsis: Optional[str]) -> str:
    """Never raises: a NULL synopsis is a normal catalogue state."""
    text = (synopsis or "").strip()
    if not text:
        return NO_SYNOPSIS
    return f"{text[:MAX_SYNOPSIS_CHARS]}..."


def _tag_names(tags: Any) -> List[str]:
    if not isinstance(tags, list):
        return []
    return [t["name"] for t in tags if isinstance(t, dict) and t.get("name")]


def _candidate_line(index: int, manga: Any) -> str:
    title = (
        getattr(manga, "title_english", None)
        or getattr(manga, "title_romaji", None)
        or "(untitled)"
    )
    return (
        f"{index}. id={getattr(manga, 'id', None)}, title=\"{title}\", "
        f"genres={getattr(manga, 'genres', None) or []}, "
        f"tags={_tag_names(getattr(manga, 'tags', None))}, "
        f"synopsis=\"{_synopsis_excerpt(getattr(manga, 'synopsis', None))}\"\n"
    )


def _items(parsed: Any) -> Iterable[Any]:
    """Accept the documented object, a bare list, or any object holding a list."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, list):
                return value
    return []


def _reasoning_map(parsed: Any) -> Dict[int, str]:
    reasoning: Dict[int, str] = {}
    for item in _items(parsed):
        if not isinstance(item, dict):
            continue
        try:
            manga_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        sentence = item.get("reasoning")
        if not isinstance(sentence, str):
            continue
        sentence = sentence.strip()
        if sentence:
            reasoning[manga_id] = sentence
    return reasoning


async def generate_reasoning(
    query: str, candidates: List[Dict[str, Any]]
) -> Dict[int, str]:
    """Return ``{manga_id: one sentence}``; empty on any failure."""
    if not client or not candidates or not settings.LLM_REASONING_ENABLED:
        return {}

    try:
        lines = []
        for index, candidate in enumerate(candidates):
            manga = candidate.get("manga") if isinstance(candidate, dict) else None
            if manga is None:
                continue
            lines.append(_candidate_line(index + 1, manga))
        if not lines:
            return {}

        user_prompt = f"Request: \"{query}\"\n\nCandidates:\n{''.join(lines)}"

        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=settings.LLM_REASONING_MODEL,
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=settings.LLM_REASONING_TIMEOUT_S,
        )

        content = chat_completion.choices[0].message.content
        if not content:
            return {}

        return _reasoning_map(json.loads(content))
    except Exception as e:
        _report_failure(e)
        return {}
