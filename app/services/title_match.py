"""Resolving a query that names a title (ARCH-10).

Split out of `retrieval.py`. Two different questions live here, and the split
between them is the point (SVC-12):

* `find_exact_title` - the query *is* a title, verbatim. Unambiguous intent, so
  it keeps the fast path and may replace the search.
* `find_title_suggestion` - the query is *close* to a title. Typos are
  tolerated, but the answer is advisory: it is offered beside the thematic
  results, never instead of them.

`is_confident_title_match` is the rule that stops a verbatim word fragment (a
theme, not a title) from being read as an intent.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings


def is_confident_title_match(query: str, title: Optional[str], sim: float, word_sim: float) -> Tuple[bool, str]:
    """Should a fuzzy trigram hit be treated as "the user typed this title"?

    Returns (accepted, reason_if_rejected) so callers and tests can say why.

    The old rule was `match_score >= 0.48 or sim >= 0.40 or word_sim >= 0.65`.
    The `word_sim >= 0.65` arm is the problem: `word_similarity` is 1.000
    whenever one query word occurs in the title, so "cooking", "survival" and
    "detective" all resolved to a single title. Measured: 10 of 12 thematic
    queries took the title branch.

    A verbatim word fragment is therefore rejected. A misspelling cannot appear
    verbatim in a title -- over 8 measured misspellings the highest
    word_similarity is 0.933 -- so this veto costs no typo tolerance. It is also
    the only rule here that does not need re-tuning as the catalogue grows.
    """
    if not query or not title:
        return False, "no-title"

    q = query.strip().lower()
    t = title.strip().lower()
    if not q or not t:
        return False, "no-title"

    # The user typed the title exactly; the exact-match query already caught that
    # case, so reaching here with identical text means a different row collided.
    if q == t:
        return True, ""

    if word_sim >= settings.TITLE_MATCH_MAX_WORD_SIM:
        return False, "verbatim-fragment"

    if sim < settings.TITLE_MATCH_MIN_SIM:
        return False, "similarity"

    coverage = len(q) / len(t)
    if not (settings.TITLE_MATCH_MIN_COVERAGE <= coverage <= settings.TITLE_MATCH_MAX_COVERAGE):
        return False, "coverage"

    return True, ""


async def find_exact_title(
    session: AsyncSession,
    query: Optional[str] = None
) -> Optional[Tuple[int, str, List[float], float]]:
    """Resolve a query that is *exactly* a title (or alternative title).

    This is the only branch that is allowed to replace the search. Typing a
    title verbatim is an unambiguous intent, and the lookup is one indexed
    query, so keeping it as a fast path costs nothing.

    Returns (manga_id, matched_title, embedding_list, 1.0) or None.
    """
    if not query or not query.strip():
        return None
    clean_q = query.strip().lower()
    if len(clean_q) < 3:
        return None

    res = await session.execute(text("""
        SELECT id, title_english, title_romaji, embedding::real[], popularity
        FROM manga
        WHERE (
            LOWER(title_english) = :q 
            OR LOWER(title_romaji) = :q
            OR LOWER(COALESCE(title_native, '')) = :q
            OR EXISTS (
                SELECT 1
                FROM unnest(COALESCE(alternative_titles, '{}')) AS alt(t)
                WHERE LOWER(t) = :q
            )
        )
          AND embedding IS NOT NULL
        ORDER BY popularity DESC NULLS LAST
        LIMIT 1;
    """), {'q': clean_q})
    exact = res.fetchone()
    if exact:
        try:
            return exact[0], exact[1] or exact[2], exact[3], 1.0
        except Exception:
            pass
    return None


async def find_title_suggestion(
    session: AsyncSession,
    query: Optional[str] = None
) -> Optional[Tuple[int, str, List[float], float]]:
    """Look for a *close* title to offer alongside a thematic search.

    This used to be `find_matched_title`, and its result *replaced* the search:
    "monster hunting" resolved to *Monster Hunter* and the thematic results
    were never computed. Five measured thematic phrases were hijacked this way
    (`monster hunting`, `time travel`, `romance between rivals`,
    `isekai with a weak protagonist`, `villainess reincarnation`).

    Raising the threshold instead was measured and rejected: `sim >= 0.75`
    clears all five hijacks but loses 3 of 8 misspellings.

    The honest fix is to stop choosing for the user. This function still
    tolerates typos, but its answer is now a *suggestion* shown next to the
    real thematic results, never a replacement for them.

    Returns (manga_id, matched_title, embedding_list, match_score) or None.
    """
    if not query or not query.strip():
        return None
    clean_q = query.strip().lower()
    if len(clean_q) < 3:
        return None

    # 2. Fast Trigram / word similarity match using GIN indexes
    # One round-trip and transaction-local, so pooled connections never inherit these.
    await session.execute(text(
        "SELECT set_config('pg_trgm.word_similarity_threshold', '0.40', true), "
        "set_config('pg_trgm.similarity_threshold', '0.30', true);"
    ))
    res = await session.execute(text("""
        SELECT id, title_english, title_romaji, embedding::real[], popularity,
               GREATEST(similarity(:q, LOWER(COALESCE(title_english, ''))), similarity(:q, LOWER(COALESCE(title_romaji, '')))) as sim,
               GREATEST(word_similarity(:q, LOWER(COALESCE(title_english, ''))), word_similarity(:q, LOWER(COALESCE(title_romaji, '')))) as w_sim,
               (
                   0.55 * GREATEST(similarity(:q, LOWER(COALESCE(title_english, ''))), similarity(:q, LOWER(COALESCE(title_romaji, ''))))
                   + 0.25 * GREATEST(word_similarity(:q, LOWER(COALESCE(title_english, ''))), word_similarity(:q, LOWER(COALESCE(title_romaji, ''))))
                   + 0.20 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
               ) as match_score
        FROM manga
        WHERE (:q <% title_english OR :q <% title_romaji OR title_english % :q OR title_romaji % :q)
          AND embedding IS NOT NULL
        ORDER BY match_score DESC
        LIMIT 5;
    """), {'q': clean_q})

    # A few candidates rather than one: the best-scoring hit may be a verbatim
    # word fragment (a theme, not a title) while the second is the real title.
    for mid, t_en, t_ro, emb, pop, sim, w_sim, score in res.fetchall():
        name = t_en or t_ro
        accepted, _reason = is_confident_title_match(clean_q, name, float(sim), float(w_sim))
        if accepted:
            return mid, name, emb, float(score)

    return None
