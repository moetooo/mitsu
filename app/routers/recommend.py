import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import (
    RecommendRequest,
    RecommendResponse,
    RecommendationResult,
    RouletteRequest,
    TitleSuggestion,
)
from ..services import catalog
from ..db import get_db
from ..services.embedding import generate_embedding
from ..services.retrieval import (
    SEED_MIN_SIMILARITY,
    retrieve_catalog_page,
    retrieve_similar_manga,
)
from ..services.roulette import retrieve_roulette_manga
from ..services.title_match import find_exact_title, find_title_suggestion
from ..services.llm import generate_reasoning
from ..services.cache import get_cached, set_cached, generate_cache_key
from ..services.search_autocorrect import autocorrect_query
from ..utils.sanitizer import sanitize_search_query, sanitize_recommend_filters

router = APIRouter()

@router.post("/roulette", response_model=RecommendationResult)
async def roulette(request: RouletteRequest, db: AsyncSession = Depends(get_db)):
    request.filters = sanitize_recommend_filters(request.filters)
    results = await retrieve_roulette_manga(
        db, 
        filters=request.filters, 
        seen_ids=request.seen_ids, 
        pool_limit=1,
        session_id=request.session_id
    )
    if not results:
        # Keep the caller's filters and seen set on the fallback. Dropping them
        # leaked NSFW titles past the safety predicate and could repeat the card
        # just shown; the retriever relaxes the seen set itself only when every
        # candidate has been seen.
        results = await retrieve_roulette_manga(
            db,
            filters=request.filters,
            seen_ids=request.seen_ids,
            pool_limit=1,
            session_id=request.session_id,
        )
    
    if not results:
        # Nothing in the catalog matches these filters. Returning the old
        # placeholder card (id=0, "Unknown Title") put a fake row in the feed and
        # made an empty result indistinguishable from a real recommendation.
        raise HTTPException(
            status_code=404,
            detail="no manga matches the current filters",
        )

    item = results[0]
    return RecommendationResult(
        id=item.get("id", 0),
        anilist_id=item.get("anilist_id"),
        mal_id=item.get("mal_id"),
        title=item.get("title", "Unknown Title"),
        cover_image_url=item.get("cover_image_url"),
        cover_candidates=item.get("cover_candidates"),
        banner_image=item.get("banner_image"),
        synopsis=item.get("synopsis"),
        genres=item.get("genres"),
        tags=item.get("tags"),
        status=item.get("status"),
        start_year=item.get("start_year"),
        chapters=item.get("chapters"),
        volumes=item.get("volumes"),
        average_score=item.get("average_score"),
        similarity_score=item.get("similarity_score"),
        llm_reasoning="Discovery Roulette candidate.",
        format_type=item.get("format_type"),
        is_nsfw=item.get("is_nsfw"),
    )

@router.post("/roulette/batch", response_model=List[RecommendationResult])
async def roulette_batch(request: RouletteRequest, db: AsyncSession = Depends(get_db)):
    request.filters = sanitize_recommend_filters(request.filters)
    count = request.count if request.count > 0 else 5
    results = await retrieve_roulette_manga(
        db, 
        filters=request.filters, 
        seen_ids=request.seen_ids, 
        pool_limit=count,
        session_id=request.session_id
    )
    out = []
    for item in results:
        out.append(RecommendationResult(
            id=item.get("id", 0),
            anilist_id=item.get("anilist_id"),
            mal_id=item.get("mal_id"),
            title=item.get("title", "Unknown Title"),
            cover_image_url=item.get("cover_image_url"),
            cover_candidates=item.get("cover_candidates"),
            banner_image=item.get("banner_image"),
            synopsis=item.get("synopsis"),
            genres=item.get("genres"),
            tags=item.get("tags"),
            status=item.get("status"),
            start_year=item.get("start_year"),
            chapters=item.get("chapters"),
            volumes=item.get("volumes"),
            average_score=item.get("average_score"),
            similarity_score=item.get("similarity_score"),
            llm_reasoning="Discovery Roulette candidate.",
            format_type=item.get("format_type"),
            is_nsfw=item.get("is_nsfw"),
        ))
    return out


class _Answer:
    """What one query produced: rows, the effective query, and the timings."""

    __slots__ = (
        "top_candidates", "corrected_query", "title_suggestion",
        "query_embedding_ms", "retrieval_ms", "has_more",
    )

    def __init__(self, top_candidates, corrected_query, title_suggestion,
                 query_embedding_ms, retrieval_ms, has_more):
        self.top_candidates = top_candidates
        self.corrected_query = corrected_query
        self.title_suggestion = title_suggestion
        self.query_embedding_ms = query_embedding_ms
        self.retrieval_ms = retrieval_ms
        self.has_more = has_more


async def _answer_query(db: AsyncSession, request: RecommendRequest) -> _Answer:
    """Answer one query: exact-title neighbourhood, or a thematic search.

    Kept separate from the handler because the handler may run it **twice**: the
    prompt is answered as typed first, and only when that finds nothing is the
    spelling corrected (SVC-05). Rewriting a query that works is what used to
    make a search for a character name return something else entirely.
    """
    # A query that is *exactly* a title is an unambiguous intent, so it keeps
    # the old fast path: resolve the title, then serve things similar to it.
    #
    # Anything else -- including a close-but-not-exact title -- now runs the
    # thematic search it asked for. That branch used to be taken by
    # `find_matched_title`, whose fuzzy hit *replaced* the search: "monster
    # hunting" returned *Monster Hunter* and the thematic results were never
    # computed. The close title is still offered, as a suggestion beside the
    # results rather than instead of them.
    matched_title = await find_exact_title(db, request.query) if request.query else None

    # A suggestion is computed alongside every thematic search. It is cheap (one
    # trigram query) and only becomes part of the response when a confident
    # close title exists.
    title_suggestion = None
    if request.query and not matched_title and request.page == 1:
        close = await find_title_suggestion(db, request.query)
        if close:
            sug_id, sug_name, _sug_emb, sug_score = close
            sug = await catalog.get_title_card(db, sug_id)
            if sug:
                title_suggestion = TitleSuggestion(
                    id=sug["id"],
                    title=sug["title"] or sug_name,
                    cover_image_url=sug["cover_image_url"],
                    cover_candidates=sug.get("cover_candidates"),
                    format_type=sug["format_type"],
                    start_year=sug["start_year"],
                    match_score=round(float(sug_score), 4),
                )
    
    if matched_title:
        mid, matched_name, target_emb, _ = matched_title
        corrected_query = matched_name
        query_embedding_ms = 0.0
        
        t0 = time.time()
        # Bound before the pagination branch: page >= 2 never loads the target, so
        # the optional argument below used to raise UnboundLocalError.
        target_manga = None
        top_candidates = []
        if request.page == 1:
            target_manga = await catalog.get_manga(db, mid)
            if target_manga:
                top_candidates.append({
                    "manga": target_manga,
                    # The seed is the title the user typed, so there is no
                    # query-to-title similarity to report. It used to be a
                    # hardcoded 0.96, which rendered as a fabricated "96% match".
                    "similarity_score": None,
                    "hybrid_score": None,
                    "format_type": getattr(target_manga, "format_type", None)
                })
        
        needed_limit = request.limit - len(top_candidates) if request.page == 1 else request.limit
        target_offset = 0 if request.page == 1 else ((request.page - 1) * request.limit - 1)
        
        if needed_limit > 0:
            similar_candidates = await retrieve_similar_manga(
                session=db,
                query_embedding=target_emb,
                filters=request.filters,
                # One extra row answers has_more without a second query.
                limit=needed_limit + 1,
                offset=target_offset,
                # The seed title is fetched by id above; excluding it here keeps
                # the page boundary exact instead of consuming a spare row.
                exclude_id=mid,
                query_inferred_tags=getattr(target_manga, "inferred_tags", None) if target_manga else None,
                sort=request.sort,
                # Word-matching titles are part of an exact-title answer too:
                # "berserk" also offers "Berserk of Gluttony". The word rule
                # (`title_boost > 0`) admits rows below the 0.44 floor; the
                # floor still applies to everything else.
                query_text=request.query,
                # Neighbours of a title still have to be neighbours. Without
                # this floor a sparse pool appended rows from outside the
                # neighbourhood (Berserk -> "Black Witch Mirror", sim 0.34).
                min_similarity=SEED_MIN_SIMILARITY,
            )
            for c in similar_candidates:
                top_candidates.append(c)
                if len(top_candidates) > request.limit:
                    break
        has_more = len(top_candidates) > request.limit
        top_candidates = top_candidates[:request.limit]
        retrieval_ms = (time.time() - t0) * 1000
        return _Answer(top_candidates, corrected_query, title_suggestion,
                       query_embedding_ms, retrieval_ms, has_more)
    else:
        # Standard semantic / thematic search
        t0 = time.time()
        query_embedding = await generate_embedding(request.query)
        query_embedding_ms = (time.time() - t0) * 1000
        
        offset = (request.page - 1) * request.limit
        t0 = time.time()
        top_candidates = await retrieve_similar_manga(
            session=db,
            query_embedding=query_embedding,
            filters=request.filters,
            limit=request.limit + 1,
            offset=offset,
            query_text=request.query,
            sort=request.sort
        )
        has_more = len(top_candidates) > request.limit
        top_candidates = top_candidates[:request.limit]
        retrieval_ms = (time.time() - t0) * 1000
        return _Answer(top_candidates, request.query, title_suggestion,
                   query_embedding_ms, retrieval_ms, has_more)


async def _answer_with_fallback(db: AsyncSession, request: RecommendRequest) -> _Answer:
    """Answer as typed; ask about spelling only when the answer is empty.

    This is SVC-05's fix, extracted so the rule can be tested without a catalog,
    an embedding model or an LLM. The old order corrected **first**, which meant
    every request paid a database read and a vocabulary scan, and a query the
    user could read (`romance between rivals` -> `romance between rival`) was
    silently searched as something else.
    """
    answer = await _answer_query(db, request)
    if answer.top_candidates or not request.query or request.page != 1:
        return answer

    typed_query = request.query
    corrected = await autocorrect_query(typed_query, db)
    if corrected == typed_query:
        return answer

    request.query = corrected
    retry = await _answer_query(db, request)
    if retry.top_candidates:
        return retry

    request.query = typed_query
    return answer


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: RecommendRequest, db: AsyncSession = Depends(get_db)):
    start_time = time.time()

    # Sanitize query and filter payload. Note what is *not* here: the spelling
    # correction. It used to run before the cache lookup, so every request paid a
    # database read and a vocabulary scan (SVC-05), and it rewrote queries that
    # worked. It now runs only when the answer is empty, below.
    request.query = sanitize_search_query(request.query)
    request.filters = sanitize_recommend_filters(request.filters)

    # 1. Check Cache
    # Versioned: a ranking change must not keep serving the previous algorithm's
    # payloads for an hour. Bump the prefix whenever the shape of the answer
    # changes, not only when the fields do.
    cache_key = generate_cache_key("recommend:v4", request.model_dump())
    cached_response = await get_cached(cache_key)
    if cached_response:
        return cached_response

    # 2. No query is a browse request: the filters are the whole intent, so
    #    there is nothing to embed, nothing to autocorrect and no title to
    #    suggest. This branch used to be an empty response, which is what made
    #    filter-only discovery impossible.
    if not request.query:
        t0 = time.time()
        offset = (request.page - 1) * request.limit
        top_candidates = await retrieve_catalog_page(
            db,
            filters=request.filters,
            sort=request.sort,
            limit=request.limit + 1,
            offset=offset,
        )
        has_more = len(top_candidates) > request.limit
        top_candidates = top_candidates[:request.limit]
        corrected_query = None
        title_suggestion = None
        query_embedding_ms = 0.0
        retrieval_ms = (time.time() - t0) * 1000
    else:
        # 3. Answer the query as typed, falling back to a spelling correction only
        #    if nothing matched (SVC-05). `autocorrect_query` returns its input
        #    unchanged when it has no confident candidate, so an unknown word is
        #    never replaced.
        answer = await _answer_with_fallback(db, request)

        top_candidates = answer.top_candidates
        corrected_query = answer.corrected_query
        title_suggestion = answer.title_suggestion
        query_embedding_ms = answer.query_embedding_ms
        retrieval_ms = answer.retrieval_ms
        has_more = answer.has_more

    # If no matching candidates (e.g. gibberish or zero-relevance query), skip LLM and return empty
    if not top_candidates:
        response = RecommendResponse(
            results=[],
            corrected_query=corrected_query,
            query_embedding_ms=query_embedding_ms,
            retrieval_ms=retrieval_ms,
            llm_ms=0.0,
            total_duration_ms=(time.time() - start_time) * 1000,
            has_more=False,
            title_suggestion=title_suggestion,
        )
        await set_cached(cache_key, response.model_dump(), ttl=1800)
        return response

    # 4. LLM Reasoning. A browse request has no query to reason about, and the
    #    reasoning text is rendered nowhere, so filter-only discovery stays off
    #    the paid path.
    if request.query:
        t0 = time.time()
        reasoning_map = await generate_reasoning(corrected_query, top_candidates)
        llm_ms = (time.time() - t0) * 1000
    else:
        reasoning_map = {}
        llm_ms = 0.0
    
    # 5. Format Response
    results = []
    for c in top_candidates:
        m = c["manga"]
        results.append(RecommendationResult(
            id=m.id,
            anilist_id=m.anilist_id,
            title=m.title_english or m.title_romaji or m.title_native or "Unknown Title",
            cover_image_url=m.cover_image_url,
            cover_candidates=m.cover_candidates,
            synopsis=m.synopsis,
            genres=m.genres,
            tags=m.tags,
            status=m.status,
            start_year=m.start_year,
            chapters=m.chapters,
            volumes=m.volumes,
            average_score=m.average_score,
            popularity=m.popularity,
            similarity_score=c["similarity_score"],
            llm_reasoning=reasoning_map.get(m.id),
            format_type=getattr(m, "format_type", None) or c.get("format_type"),
            inferred_tags=getattr(m, "inferred_tags", None),
            is_nsfw=getattr(m, "is_nsfw", None),
        ))
        
    response = RecommendResponse(
        results=results,
        corrected_query=corrected_query,
        query_embedding_ms=query_embedding_ms,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms,
        total_duration_ms=(time.time() - start_time) * 1000,
        has_more=has_more,
        title_suggestion=title_suggestion,
    )
    
    # 6. Cache and return
    await set_cached(cache_key, response.model_dump())
    return response
