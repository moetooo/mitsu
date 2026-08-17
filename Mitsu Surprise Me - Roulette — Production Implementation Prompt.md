# Mitsu — Surprise Me / Roulette
## Production Performance, Uniqueness & Discovery Rework

You are a **Principal Full-Stack Engineer and Performance Architect** working directly inside the existing Mitsu repository:

```text
d:\projects\recommend_tool
```

Your task is to **inspect the existing implementation first**, then incrementally rework the `Surprise Me / Roulette` feature into a fast, cached, diverse, genuinely non-repetitive discovery system.

The goal is **not simply to make random selection faster**.

The goal is:

> **Instant-feeling Surprise Me + strong uniqueness + meaningful discovery variety + reliable production behavior.**

Do not rewrite unrelated recommendation functionality.

---

# 1. NON-NEGOTIABLE OBJECTIVES

The final system must satisfy all of these:

### Performance

1. Remove `ORDER BY RANDOM()` from the Roulette path.
2. A normal user click should not wait for PostgreSQL candidate generation when a Redis candidate pool is available.
3. Candidate generation/refilling must happen asynchronously before the user needs the next candidates.
4. Frontend transitions should feel effectively instantaneous.
5. Preload cover images so cards do not visibly flicker or wait for images.

### Uniqueness

6. Never intentionally return the same manga twice within the active discovery session while enough eligible titles remain.
7. Prevent duplicates inside a generated Redis pool.
8. Prevent duplicates across pool refills.
9. Prevent immediate repeats such as:

```text
A → A
```

and repeated short cycles such as:

```text
A → B → A
```

unless the eligible candidate space is genuinely exhausted.
10. Avoid multiple entries from the same franchise/series when reliable existing identifiers are available.

### Discovery quality

11. Do not confuse "random" with "good discovery".
12. Results must have meaningful variation across:
    - genres
    - Manga / Manhwa / Manhua
    - score ranges
    - popularity
    - author where reliable
    - status where useful
    - franchise/series
13. Quality must remain the primary constraint.
14. Reserve a configurable portion of the candidate pool for less-obvious/hidden-gem titles when the available data supports it.
15. Do not use an LLM for this.
16. Do not invent fake similarity/relevance signals.

### Reliability

17. Existing filters must continue working.
18. Restrictive filters must not cause infinite generation loops.
19. Filters must never be silently disabled just to fill a pool.
20. Concurrent refill operations must not generate duplicate/racing pools.
21. Redis failure must have a safe PostgreSQL fallback that still does not use `ORDER BY RANDOM()`.
22. Measure the performance improvement rather than assuming it.

---

# 2. FIRST STEP — INSPECT THE ACTUAL REPOSITORY

**Do not start coding immediately.**

First inspect the existing implementation.

At minimum inspect:

```text
app/routers/recommend.py
app/services/retrieval.py
app/services/cache.py
frontend/src/App.jsx
frontend/src/components/SurpriseView.jsx
```

Also inspect:

```text
database models
Alembic migrations
PostgreSQL indexes
Redis initialization/utilities
RecommendationResult
RouletteRequest
existing roulette filters
existing frontend state flow
existing similarity_score usage
```

Determine:

- current manga schema
- primary key
- existing indexes
- available randomization fields
- genre representation
- format/type representation
- author representation
- AniList IDs
- title normalization fields
- score fields
- popularity fields
- status fields
- existing franchise/series identifiers
- Redis client/version/API
- current caching conventions
- whether `/roulette` is used anywhere else
- whether `similarity_score` is displayed or consumed by frontend code

**Do not assume fields exist.**

If a proposed optimization depends on a field/index that does not exist, inspect the schema and choose the smallest appropriate alternative.

---

# 3. TARGET ARCHITECTURE

The target architecture should conceptually become:

```text
                    ┌──────────────────────────┐
                    │ Background Candidate     │
                    │ Generator / Refiller     │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ PostgreSQL               │
                    │ Efficient Random Sampling│
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Eligibility / Quality    │
                    │ Filtering                │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Uniqueness Filtering     │
                    │ + Franchise Dedup        │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Diversity Selection      │
                    │ Genre / Format / Score   │
                    │ / Popularity / Author    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Controlled Randomization  │
                    │ + Exploration Allocation  │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Redis Candidate Pool      │
                    │ roulette:pool:{hash}     │
                    └────────────┬─────────────┘
                                 │
                              LPOP
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Frontend Buffer           │
                    │ 5–10+ ready candidates    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                              User
```

The key principle is:

> **PostgreSQL generates candidates. Redis stores ready-to-serve candidates. The frontend consumes them.**

The user's click should normally be a cheap queue consumption operation rather than a recommendation-generation operation.

---

# 4. REDIS CANDIDATE POOLS

Create a Redis pool per relevant filter fingerprint:

```text
roulette:pool:{filter_hash}
```

The filter hash must include every filter that changes candidate eligibility, including whatever actually exists in the current application, such as:

```text
status
min_year
max_year
min_score
min_chapters
max_chapters
genres
excluded_genres
format_type
nsfw
other roulette-affecting filters
```

Do not create permanent pools for every possible filter combination.

Use configurable TTLs.

Common/default filter pools may have longer TTLs.

Rare/custom filter combinations should expire sooner.

---

# 5. POOL SIZE AND REFILL

Start with configurable constants approximately:

```python
ROULETTE_POOL_TARGET = 75
ROULETTE_REFILL_THRESHOLD = 20
ROULETTE_GENERATION_MULTIPLIER = 2
```

Do not scatter magic numbers throughout the implementation.

Conceptually:

```text
75 → consume
50 → consume
30 → consume
20 → trigger background refill
19 → continue serving
...
```

The current request must **not wait for refill**.

If the pool is empty:

1. attempt a safe synchronous fallback generation path
2. never use `ORDER BY RANDOM()`
3. return an available valid candidate if possible
4. never fabricate a candidate

---

# 6. CONCURRENCY-SAFE REFILL

This is mandatory.

Multiple requests may notice:

```text
pool_size <= threshold
```

at the same time.

Do not allow all of them to generate refill batches simultaneously.

Use an appropriate Redis lock or equivalent atomic mechanism:

```text
roulette:refill-lock:{filter_hash}
```

The lock must:

- have an expiration
- prevent duplicate refill work
- safely release after generation
- avoid deadlocks
- tolerate process failure

Expected behavior:

```text
Request A sees pool=19
Request B sees pool=19

A acquires refill lock
B sees lock already exists
B continues serving without starting another refill

A generates candidates
A pushes candidates
A releases lock
```

---

# 7. DATABASE RANDOM SAMPLING

Remove:

```sql
ORDER BY RANDOM()
```

from the Roulette path.

Do **not blindly implement a sampling strategy before inspecting the schema.**

Evaluate the existing schema/indexes and choose the most appropriate approach from options such as:

1. indexed/precomputed random key
2. random ID/range sampling
3. PostgreSQL `TABLESAMPLE`
4. another indexed strategy appropriate to the actual schema

For a typical large PostgreSQL table, an indexed/precomputed random key is a strong candidate.

If appropriate, add an Alembic migration such as:

```sql
ALTER TABLE manga
ADD COLUMN random_rank double precision DEFAULT random();

CREATE INDEX idx_manga_random_rank
ON manga(random_rank);
```

But **only do this after confirming that it is appropriate for the actual schema.**

For an indexed random-rank implementation, use an anchor/range strategy rather than sorting the entire table:

```sql
WHERE <filters>
  AND random_rank >= :anchor
ORDER BY random_rank
LIMIT :n
```

with wrap-around:

```sql
WHERE <filters>
  AND random_rank < :anchor
ORDER BY random_rank
LIMIT :remaining
```

Verify using:

```sql
EXPLAIN ANALYZE
```

that the new query does not revert to a sequential scan + random sort.

---

# 8. OVER-FETCH CANDIDATES

Never generate exactly the number of candidates needed.

For example:

```text
Need 75
↓
retrieve ~150–300
↓
remove ineligible/seen/duplicate candidates
↓
diversity selection
↓
controlled randomization
↓
store best ~75
```

Make the multiplier configurable.

The exact candidate count should depend on actual rejection rates.

If the pool is restrictive, do not repeatedly query forever trying to reach the target.

---

# 9. MULTI-LEVEL UNIQUENESS

Uniqueness is a **first-class requirement**, not a frontend convenience.

## A. Duplicate manga IDs

Never put the same:

```text
manga.id
```

into the same active pool.

## B. Session-level uniqueness

Generate a client session ID:

```javascript
crypto.randomUUID()
```

Store it in memory rather than localStorage unless the existing architecture requires otherwise.

Use:

```text
roulette:seen:{session_id}
```

in Redis.

When a candidate is actually shown:

```text
SADD roulette:seen:{session_id} manga_id
EXPIRE roulette:seen:{session_id} ...
```

The backend must be authoritative.

Do not rely only on a frontend `seen_ids` array.

## C. Pool/refill uniqueness

When generating a new pool/refill, exclude:

```text
currently queued IDs
+
recently shown IDs
+
recently generated IDs
```

where practical.

This prevents:

```text
Pool 1:
A B C D E

Pool 2:
A B F G H
```

## D. Immediate repeat prevention

Avoid:

```text
A → A
```

and:

```text
A → B → A
```

unless the eligible candidate space is genuinely exhausted.

## E. Same-series prevention

Inspect existing identifiers first.

If reliable fields such as AniList IDs or existing series/franchise grouping are available, prevent multiple versions of the same series from occupying one pool.

Do not invent a complicated new franchise-detection system if the data does not support it.

---

# 10. DIVERSITY SELECTION

Uniqueness alone is not enough.

This:

```text
A
B
C
D
E
```

can still feel repetitive if all five are essentially the same type of manga.

The pool must provide meaningful exploration.

Use lightweight rule-based diversity.

Do **not** use embeddings or an LLM for this unless the existing architecture already provides a cheap reliable signal.

Consider:

- genre
- format
- score
- popularity
- author
- status
- franchise/series identity
- existing legitimate recommendation/relevance signal

A practical selection algorithm:

```text
retrieve candidates
        ↓
remove seen/duplicate/invalid candidates
        ↓
score candidates
        ↓
greedily select diverse candidates
        ↓
apply soft constraints
        ↓
controlled randomization
```

For small pools, an in-memory greedy algorithm is sufficient.

---

# 11. GENRE DIVERSITY

Track genre counts while selecting.

For example, for a 30-item candidate batch:

```text
maximum representation of one genre ≈ 25–30%
```

Do not make this a hard failure if the filtered candidate universe genuinely contains only one genre.

The system should distinguish:

```text
available diversity
```

from:

```text
forced diversity
```

Never inject irrelevant titles just to satisfy a diversity percentage.

---

# 12. FORMAT DIVERSITY

When the user has not explicitly selected a format, attempt to maintain a healthy mixture of:

```text
Manga
Manhwa
Manhua
```

when enough eligible candidates exist.

When the user explicitly filters to one format, respect that filter completely.

---

# 13. SCORE-BAND DIVERSITY

Avoid generating a pool where every result is from the same score band.

Possible buckets:

```text
< 7
7–8
8–9
9+
```

Do not allow one bucket to dominate when sufficient alternatives exist.

Again, this is a soft diversity objective rather than a reason to violate user filters.

---

# 14. POPULARITY / HIDDEN-GEM EXPLORATION

This is a critical part of Mitsu.

Do not make:

```text
Surprise Me = highest-rated manga shuffled randomly
```

Instead create controlled exploration.

Conceptually:

```text
60–70% high-confidence candidates
20–30% less-obvious / hidden-gem candidates
~10% experimental candidates
```

These percentages must be configurable and should be adjusted based on the actual data distribution.

"Hidden gem" must be based on real existing signals such as:

- reasonable score
- lower popularity
- lower readership count
- sufficient metadata quality
- existing relevance score where legitimate

Do not invent fake scores.

Do not claim:

```text
average_score / 100
```

is semantic similarity.

If `similarity_score` currently means something else, inspect all frontend/backend consumers before changing it.

---

# 15. CONTROLLED RANDOMNESS

Do not make every candidate equally likely.

Use lightweight weighted selection based only on real available signals.

Possible signals:

```text
quality
existing recommendation relevance
popularity adjustment
novelty
metadata completeness
```

The final system should behave approximately like:

```text
quality constraint
        +
relevance constraint
        +
novelty
        +
diversity
        +
controlled randomness
```

rather than:

```text
pure random()
```

The user should feel:

> "I didn't expect this, but this is actually worth checking."

---

# 16. FRONTEND BUFFER

The backend/Redis layer remains authoritative for discovery and uniqueness.

The frontend should still maintain a small local buffer for perceived latency.

Use something like:

```text
rouletteBuffer
```

with approximately:

```text
5–10 candidates
```

or another value determined by actual UX/testing.

Flow:

```text
click
 ↓
consume local candidate
 ↓
immediately render
 ↓
if buffer low:
    asynchronously request more
```

Do not block the click on a network request when a local candidate exists.

---

# 17. IMAGE PRELOADING

Whenever candidates enter the frontend buffer, preload their cover images.

Use browser caching via something equivalent to:

```javascript
const img = new Image();
img.src = item.cover_image_url;
```

Preload asynchronously.

Do not block candidate consumption while waiting for images.

Goal:

```text
candidate already available
+
cover already warm in browser cache
=
smooth card transition
```

This is a UX optimization, not part of uniqueness logic.

---

# 18. FILTER CHANGES

Filter changes must invalidate stale candidates.

When filters change:

```text
clear frontend buffer
clear pending frontend refill state
switch to new filter fingerprint
fetch/generate candidates for new filters
```

Never display candidates generated under the previous filter configuration.

The Redis pool key must include all relevant filters.

---

# 19. RESTRICTIVE FILTERS

Example:

```text
Completed
+
Fantasy
+
Score > 90
+
< 20 chapters
```

If only 8 eligible manga exist:

- return those 8
- do not loop indefinitely
- do not silently remove filters
- do not fabricate candidates
- do not repeatedly regenerate the same candidates
- allow reuse only when the eligible session space is exhausted and the configured cooldown/reuse policy permits it

The system must gracefully degrade.

---

# 20. REDIS FAILURE FALLBACK

If Redis is temporarily unavailable:

The system must remain functional.

Use PostgreSQL directly with the efficient sampling strategy.

However:

**Never reintroduce:**

```sql
ORDER BY RANDOM()
```

as the fallback.

The fallback should still:

```text
efficiently sample
→ filter
→ exclude seen IDs where possible
→ diversify
→ return candidate
```

Log Redis failures clearly.

---

# 21. RESPONSE DATA / CACHE STRATEGY

Evaluate whether Redis should store:

### Option A

```text
manga IDs
```

or:

### Option B

```text
IDs + lightweight RecommendationResult data
```

Prefer IDs if fetching the corresponding manga records is cheap and indexed.

If fetching complete objects creates another expensive DB request for every click, consider storing lightweight response data in Redis.

Do not duplicate the entire manga database into Redis unnecessarily.

---

# 22. API COMPATIBILITY

Preserve:

```text
POST /roulette
```

unless inspection shows a strong reason not to.

Do not unnecessarily break existing frontend/backend consumers.

If a batch endpoint is beneficial, introduce it in a backward-compatible way, for example:

```text
POST /roulette/batch
```

while preserving `/roulette` compatibility where practical.

Existing filters must continue working.

Do not silently ignore:

```text
status
year
score
chapters
genres
excluded genres
format
NSFW
```

or any additional filters discovered during repository inspection.

---

# 23. OBSERVABILITY

Add measurements so the optimization can be proven.

Track:

```text
roulette request latency
candidate generation latency
Redis pool hit
Redis pool miss
pool size
refill count
refill lock contention
candidate rejection count
duplicate rejection count
seen rejection count
generation batch size
filter fingerprint
fallback usage
```

Measure:

```text
p50 latency
p95 latency
```

before and after the change.

The target is measurable improvement.

Do not claim "0ms".

The correct goal is:

> **effectively zero perceived latency for normal buffered clicks.**

---

# 24. TESTING REQUIREMENTS

Add tests for:

### Uniqueness

Generate at least 5 consecutive pools/batches and verify:

```text
no duplicate manga IDs
```

across the active session when enough candidates exist.

### Diversity

Verify:

```text
genre distribution
format distribution
score-band distribution
```

when enough candidate diversity exists.

### Franchise dedup

Verify that multiple entries from the same known series are not unnecessarily placed in one pool.

### Restrictive filters

Verify that a small eligible pool:

```text
terminates
returns available candidates
does not loop
does not remove filters
```

### Concurrency

Simulate multiple refill triggers and verify:

```text
only one refill generator runs
no duplicate pool insertion occurs
```

### Filter changes

Verify stale frontend candidates are discarded.

### Redis failure

Verify the PostgreSQL fallback works without:

```sql
ORDER BY RANDOM()
```

### Performance

Use:

```sql
EXPLAIN ANALYZE
```

to verify the new sampling query is actually efficient.

---

# 25. IMPLEMENTATION ORDER

Implement incrementally.

## Phase 0 — Audit

Inspect:

- schema
- indexes
- Redis
- router
- retrieval
- cache
- frontend
- tests
- current API consumers

Do not modify code yet.

---

## Phase 1 — Database sampling

- remove `ORDER BY RANDOM()`
- implement the chosen efficient sampling method
- add required migration/index
- verify with `EXPLAIN ANALYZE`

---

## Phase 2 — Redis candidate pool

Implement:

```text
roulette:pool:{filter_hash}
```

with:

- target size
- TTL
- candidate insertion
- LPOP serving

---

## Phase 3 — Safe refill

Add:

- refill threshold
- background refill
- Redis lock
- refill failure handling

---

## Phase 4 — Uniqueness

Add:

- session ID
- server-side seen set
- pool duplicate protection
- cross-refill exclusion
- immediate-repeat prevention
- franchise/series dedup where supported

---

## Phase 5 — Discovery quality

Add:

- genre diversity
- format diversity
- score-band diversity
- popularity balancing
- hidden-gem allocation
- controlled randomization

Keep this rule-based and cheap.

---

## Phase 6 — Frontend performance

Add:

- local roulette buffer
- background batch refill
- stale-buffer invalidation on filter changes
- image preloading
- smooth fallback loading behavior

---

## Phase 7 — Observability and testing

Add:

- latency measurements
- pool metrics
- refill metrics
- rejection metrics
- concurrency tests
- uniqueness tests
- restrictive-filter tests
- Redis failure tests

Then compare:

```text
before:
request latency
DB time

after:
p50
p95
DB time
Redis hit rate
perceived click latency
```

---

# 26. SCOPE GUARDRAILS

Do NOT:

- rewrite `/recommend`
- rewrite semantic search
- replace pgvector
- introduce an LLM
- introduce embeddings solely for Roulette
- invent fake similarity scores
- redesign the entire frontend
- remove existing filters
- silently weaken user filters
- duplicate the entire manga database into Redis
- introduce a large task-processing framework unless the existing architecture genuinely requires it
- modify unrelated recommendation behavior
- add unnecessary dependencies

Prefer modifying existing:

```text
app/services/retrieval.py
app/services/cache.py
app/routers/recommend.py
frontend/src/App.jsx
frontend/src/components/SurpriseView.jsx
```

plus required:

```text
Alembic migration
tests
```

---

# 27. IMPORTANT ENGINEERING RULES

### Rule 1

**Inspect before deciding.**

Do not blindly implement `random_rank` or any other technique if the existing schema suggests a better solution.

### Rule 2

**Do not overengineer.**

Use the smallest architecture that satisfies:

```text
performance
uniqueness
diversity
reliability
```

### Rule 3

**Quality beats artificial diversity.**

Never add irrelevant manga simply to satisfy a genre/format percentage.

### Rule 4

**Uniqueness is backend-authoritative.**

Frontend state is an optimization, not the source of truth.

### Rule 5

**Randomness is controlled, not blind.**

The feature should produce surprising results that remain worth discovering.

### Rule 6

**No fake intelligence.**

Do not invent semantic similarity, recommendation scores, or "AI" reasoning that the existing data does not support.

### Rule 7

**Measure everything important.**

Do not declare success without latency and behavior measurements.

### Rule 8

**Preserve existing behavior.**

Existing recommendation/search functionality and filters must continue working.

---

# 28. FINAL ACCEPTANCE CRITERIA

The implementation is complete only when all of the following are true:

- [ ] `ORDER BY RANDOM()` removed from Roulette
- [ ] efficient sampling verified with `EXPLAIN ANALYZE`
- [ ] Redis candidate pool implemented
- [ ] filter-aware pool keys implemented
- [ ] background refill implemented
- [ ] refill locking implemented
- [ ] session-level server-side uniqueness implemented
- [ ] cross-refill duplicate prevention implemented
- [ ] immediate-repeat prevention implemented
- [ ] franchise/series dedup implemented where reliable data exists
- [ ] diversity-aware selection implemented
- [ ] genre spread implemented
- [ ] format spread implemented
- [ ] score-band spread implemented
- [ ] controlled randomness implemented
- [ ] hidden-gem/exploration allocation implemented using real signals only
- [ ] restrictive filters handled without infinite loops
- [ ] filters never silently disabled
- [ ] Redis failure fallback implemented
- [ ] frontend local buffering implemented
- [ ] frontend background refill implemented
- [ ] filter-change buffer invalidation implemented
- [ ] image preloading implemented
- [ ] existing `/roulette` compatibility preserved where practical
- [ ] existing recommendation/search system untouched
- [ ] concurrency tests added
- [ ] uniqueness tests added
- [ ] diversity tests added
- [ ] restrictive-filter tests added
- [ ] Redis failure test added
- [ ] p50/p95 latency measured
- [ ] before/after performance comparison reported

---

# 29. DELIVERABLE

Before making changes:

1. Summarize the existing Roulette architecture you found.
2. Identify the current bottleneck.
3. Identify the actual schema/index constraints affecting random sampling.
4. Explain which sampling strategy you selected and why.
5. Identify which files will change.

Then implement the changes incrementally.

After implementation, report:

```text
Files changed
Database changes
Redis changes
Backend changes
Frontend changes
Uniqueness strategy
Diversity strategy
Concurrency strategy
Fallback strategy
Tests added
Before/after p50
Before/after p95
Remaining limitations
```

Do not rewrite unrelated code.

Do not stop at a conceptual answer.

**Inspect the repository and implement the production-ready solution.**