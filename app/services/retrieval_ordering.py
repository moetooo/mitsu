"""Ordering and similarity-floor constants for retrieval.

Extracted from `retrieval.py` (ARCH-10: that module is at its line ceiling) so
the SQL grammar can be tested and shared without importing the query builder.

Every ORDER BY ends in `id` so offset paging has a total order: rows tied on
popularity/score can otherwise repeat or vanish between pages.
"""

from typing import Optional

# Sort ids are the wire contract (`RecommendRequest.sort`). An unknown value is
# already a 422 at the model layer; normalising again here keeps the service
# callable from tests and from the browse path without a second grammar.
SORT_IDS = ("default", "relevance", "popularity")

# A title-seeded search (the user typed a title) adds the title itself and then
# asks for neighbours of its embedding. That path has no query text, so it used
# to run with *no* relevance floor at all: any row the ANN pool returned was
# accepted. A sparse pool (restrictive filters, a thin neighbourhood) could then
# append a weakly related title right under the seed -- the reported case was
# "Black Witch Mirror" at sim 0.33-0.39 under Berserk/Monogatari/Bakemonogatari.
#
# 0.44 is the same floor the text path uses (`sim >= 0.44`). Neighbours of a
# real seed sit around 0.55-0.70, so this trims noise without cutting a normal
# neighbourhood in half.
SEED_MIN_SIMILARITY = 0.44

_TEXT_ORDER_SQL = {
    "relevance": "sim DESC, hybrid_score DESC, id ASC",
    "popularity": "popularity DESC NULLS LAST, average_score DESC NULLS LAST, id ASC",
}
_DEFAULT_TEXT_ORDER = "hybrid_score DESC, id ASC"

# With no query there is no similarity, so `relevance` collapses to the default
# catalogue order. Default browse uses the same popularity x score ranking as
# `/manga/trending`; `popularity` is strictly raw popularity.
_BROWSE_ORDER_SQL = {
    "popularity": "popularity DESC NULLS LAST, average_score DESC NULLS LAST, id ASC",
}
_DEFAULT_BROWSE_ORDER = (
    "COALESCE(popularity, 0) * COALESCE(average_score, 0) DESC, "
    "average_score DESC NULLS LAST, popularity DESC NULLS LAST, id ASC"
)


def normalize_sort(sort: Optional[str]) -> str:
    return sort if sort in SORT_IDS else "default"


def text_order_clause(sort: str) -> str:
    return _TEXT_ORDER_SQL.get(normalize_sort(sort), _DEFAULT_TEXT_ORDER)


def browse_order_clause(sort: str) -> str:
    return _BROWSE_ORDER_SQL.get(normalize_sort(sort), _DEFAULT_BROWSE_ORDER)
