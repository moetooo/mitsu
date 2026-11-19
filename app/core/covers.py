"""One place that decides whether a cover URL can be shown to a browser.

Lives in `app.core` because two layers need the same rules and neither may import
the other: response models (`app/models.py`) sanitise covers before they reach a
client, and ingestion decides which cover wins a merge. `app.core` is the only
package both may depend on, and this module has no imports of its own.

The bug this exists to prevent (`cover_unavailable_resolve.md`): a cover URL was
treated as just a string, so `uploads.mangadex.org` addresses were written,
served and cached for months after that host started answering browser image
requests with a JS challenge. Every row with such a URL renders `CoverFallback`,
and nothing in the database said so.

Two rules follow from that, and they live here rather than being re-derives at
each call site:

* **A URL on a blocked host is never emitted.** Not stored, not serialised, not
  shipped to a client - the browser cannot load it, so it is not a cover.
* **A cover has a rank.** AniList outranks Kitsu outranks MangaDex outranks
  nothing. `upsert._merge_into` compares ranks instead of "first non-empty wins",
  so a later sync cannot demote a healthy cover to a dead one.

The lists below are the *defaults*. They are read from configuration at call time
(`COVER_ALLOWED_HOSTS`, `COVER_BLOCKED_HOSTS`, `COVER_SOURCE_ORDER`,
`COVER_MAX_CANDIDATES`), so banning or reinstating a host is a deploy variable
rather than a code change - which is the lesson of the MangaDex block, where the
fix waited on a release. `validate_cover_config()` checks the values at startup
and every accessor below falls back to these defaults when a value is unusable,
so a typo degrades rather than crashes.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from ..config import settings

#: Hosts measured to serve `200 image/*` to a browser-like request
#: (Chrome `User-Agent` + `Accept`). Adding a host here is a claim that a browser
#: can load it - verify with `scripts/cover_probe.py` first.
BROWSER_SAFE_HOSTS: tuple[str, ...] = (
    "s4.anilist.co",
    "media.kitsu.app",
    "cdn.myanimelist.net",
)

#: Hosts that answer browsers with a challenge page instead of an image.
BLOCKED_HOSTS: tuple[str, ...] = ("uploads.mangadex.org",)

#: Every provider name the database accepts (`ck_manga_cover_source`). A name
#: outside this set cannot be stored, so it is a configuration error, not a
#: silently-ignored entry.
KNOWN_SOURCES: tuple[str, ...] = ("anilist", "mal", "kitsu", "mangadex")

#: Default provider preference. Higher wins when two sources disagree about a
#: cover; `source_rank()` derives the live numbers from `COVER_SOURCE_ORDER`.
#: AniList first (best art at `large`), then MAL (14-50 KB, lighter than AniList's
#: 81-300 KB), then Kitsu. MangaDex is last because its image host cannot be
#: loaded by a browser at all - it only exists here so a legacy row is ranked
#: below every usable provider instead of tying with "no cover".
SOURCE_RANK: dict[Optional[str], int] = {
    "anilist": 4,
    "mal": 3,
    "kitsu": 2,
    "mangadex": 1,
    None: 0,
}

_HOST_SOURCE = {
    "anilist.co": "anilist",
    "myanimelist.net": "mal",
    "kitsu.app": "kitsu",
    "mangadex.org": "mangadex",
}


def _split(raw: Optional[str]) -> tuple[str, ...]:
    """Parse a comma-separated config value; blanks and spacing are not entries."""
    if not raw:
        return ()
    return tuple(part.strip().lower() for part in str(raw).split(",") if part.strip())


def _setting(name: str, default: Any) -> Any:
    """Read a setting, tolerating a `settings` object that predates the field."""
    return getattr(settings, name, default)


def allowed_hosts() -> tuple[str, ...]:
    """Hosts a browser is known to load, in config order."""
    return _split(_setting("COVER_ALLOWED_HOSTS", "")) or BROWSER_SAFE_HOSTS


def blocked_hosts() -> tuple[str, ...]:
    """Hosts that answer browsers with a challenge. Always wins over `allowed`."""
    configured = _setting("COVER_BLOCKED_HOSTS", "")
    # An empty string means "block nothing", which is a legitimate choice a deploy
    # may make; only an *absent* setting falls back to the historical default.
    if configured is None:
        return BLOCKED_HOSTS
    return _split(configured)


def source_order() -> tuple[str, ...]:
    """Live provider order, best first, filtered to names the database accepts."""
    order = tuple(s for s in _split(_setting("COVER_SOURCE_ORDER", "")) if s in KNOWN_SOURCES)
    return order or tuple(
        sorted((name for name in SOURCE_RANK if name), key=lambda n: -SOURCE_RANK[n])
    )


def source_rank(source: Optional[str]) -> int:
    """Preference of a provider name; 0 for unknown or absent."""
    order = source_order()
    if source in order:
        return len(order) - order.index(source)
    return 0


def max_candidates() -> int:
    """How many fallbacks a row may carry, clamped to something the renderer can use."""
    try:
        value = int(_setting("COVER_MAX_CANDIDATES", MAX_CANDIDATES))
    except (TypeError, ValueError):
        return MAX_CANDIDATES
    return max(1, min(value, 5))


def validate_cover_config() -> list[str]:
    """Problems with the cover configuration, as human-readable sentences.

    Called once at startup. The accessors above already fall back to the defaults,
    so these are warnings about intent - a host that is both allowed and blocked, a
    provider name the database rejects - not reasons to refuse to boot.
    """
    problems: list[str] = []

    # Validate what was *configured*, not what the accessor fell back to: an empty
    # value is a typo worth reporting even though it degrades to the defaults.
    allowed = _split(_setting("COVER_ALLOWED_HOSTS", ""))
    blocked = _split(_setting("COVER_BLOCKED_HOSTS", ""))
    if not allowed:
        problems.append("COVER_ALLOWED_HOSTS is empty; no cover would be considered loadable")
    for host in set(allowed) & set(blocked):
        problems.append(
            f"host {host} is in both COVER_ALLOWED_HOSTS and COVER_BLOCKED_HOSTS; "
            "it is treated as blocked"
        )
    for host in allowed + blocked:
        if "." not in host or "/" in host:
            problems.append(f"host {host!r} is not a bare hostname (e.g. s4.anilist.co)")

    raw_order = _split(_setting("COVER_SOURCE_ORDER", ""))
    unknown = [name for name in raw_order if name not in KNOWN_SOURCES]
    if unknown:
        problems.append(
            "COVER_SOURCE_ORDER names unknown provider(s) "
            f"{', '.join(unknown)}; allowed: {', '.join(KNOWN_SOURCES)}"
        )
    if raw_order and not source_order():
        problems.append("COVER_SOURCE_ORDER has no usable provider; using the default order")

    count = _setting("COVER_MAX_CANDIDATES", MAX_CANDIDATES)
    try:
        if not 1 <= int(count) <= 5:
            problems.append(f"COVER_MAX_CANDIDATES={count} is outside 1..5")
    except (TypeError, ValueError):
        problems.append(f"COVER_MAX_CANDIDATES={count!r} is not a number")

    return problems


def host_of(url: Optional[str]) -> Optional[str]:
    """Return the lower-cased host of `url`, or None if it is not a http(s) URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    return (parsed.hostname or "").lower() or None


def is_https(url: Optional[str]) -> bool:
    """True only for an https URL.

    The app is served over https, so a plain-http image is blocked as mixed
    content by every browser regardless of whether the host is healthy: it renders
    as a broken card just like the MangaDex challenge did. Providers occasionally
    hand one back, so the rule lives next to the other cover rules.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        return urlparse(url).scheme == "https"
    except ValueError:
        return False


def is_blocked(url: Optional[str]) -> bool:
    """True when the host answers browsers with a bot challenge instead of bytes."""
    host = host_of(url)
    return host in blocked_hosts()


def is_browser_safe(url: Optional[str]) -> bool:
    """True only for a URL a browser is known to be able to load.

    Unknown hosts are *not* safe by default: that assumption is what shipped
    10,621 dead covers.
    """
    host = host_of(url)
    if host in blocked_hosts():
        return False
    return host in allowed_hosts()


def cover_source_for(url: Optional[str]) -> Optional[str]:
    """Provider name for a cover URL, or None when it is unknown/absent."""
    host = host_of(url)
    if not host:
        return None
    for suffix, source in _HOST_SOURCE.items():
        if host == suffix or host.endswith("." + suffix):
            return source
    return None


def cover_rank(url: Optional[str]) -> int:
    """Preference of a cover URL; 0 for nothing usable. Blocked hosts rank 0.

    A blocked URL must not win a merge, so it is ranked worse than an absent one
    is not the point - it is ranked below every usable provider and is never
    written in the first place.
    """
    if not url or is_blocked(url):
        return 0
    return source_rank(cover_source_for(url))


def classify_cover(url: Optional[str]) -> tuple[str, str]:
    """Map a cover URL to `(cover_status, cover_source)` for storage.

    `ok` means "this host is known to serve images to browsers", which is what
    the ingest-time backfill in migration 0007 asserts too. Per-URL truth (rot,
    404s) is the verifier job's business, not ingestion's.
    """
    source = cover_source_for(url) or "none"
    if not url:
        return "unverified", "none"
    if not is_https(url) or is_blocked(url):
        # Not renderable at all: an http URL is blocked as mixed content and a
        # challenge host returns HTML, so neither is merely "unverified".
        return "dead", source
    if is_browser_safe(url):
        return "ok", source
    return "unverified", source


#: How many fallbacks a row may carry. Two is what the renderer walks in
#: practice; the third is headroom for a provider added later without a migration.
MAX_CANDIDATES = 3


def make_candidate(
    url: Optional[str],
    *,
    source: Optional[str] = None,
    variant: Optional[str] = None,
) -> Optional[dict]:
    """Build one candidate entry, or None when the URL cannot be rendered.

    Blocked hosts and non-http(s) strings are dropped here rather than at the
    edge: a candidate that cannot load is not a fallback, it is a wasted
    round-trip and another `onError`.
    """
    if not url or not is_https(url) or is_blocked(url):
        return None
    entry: dict = {"source": source or cover_source_for(url) or "unknown", "url": url}
    if variant:
        entry["variant"] = variant
    return entry


def normalise_candidates(raw: Any) -> list[dict]:
    """Coerce anything stored in `cover_candidates` into a usable ordered list.

    Tolerates NULL, a bare URL string, dicts missing `url`, duplicates and
    blocked hosts, because these values are written by several code paths over
    time and a malformed list must degrade to "no candidates", never to a crash
    in the render path.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [{"url": raw}]
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        entry = make_candidate(
            url, source=item.get("source"), variant=item.get("variant")
        )
        if not entry:
            continue
        seen.add(url)
        out.append(entry)
        if len(out) >= max_candidates():
            break
    return out


def merge_candidates(existing: Any, incoming: Any) -> list[dict]:
    """Union two candidate lists, best provider first, then original order.

    Ordering is stable so a repair run is idempotent: re-merging the same input
    twice cannot produce a different list, which is what keeps a nightly job from
    churning `updated_at` on every row.
    """
    merged: list[dict] = []
    seen: set[str] = set()
    for group in (normalise_candidates(incoming), normalise_candidates(existing)):
        for entry in group:
            url = entry["url"]
            if url in seen:
                continue
            seen.add(url)
            merged.append(entry)

    indexed = list(enumerate(merged))
    indexed.sort(key=lambda pair: (-source_rank(pair[1].get("source")), pair[0]))
    return [entry for _index, entry in indexed][: max_candidates()]


def rank_candidates(entries: list[dict]) -> list[dict]:
    """Apply the configured provider order to an already-stored list.

    Stored order is not policy: an operator who promotes MAL to first expects the
    next response to lead with MAL, without a data migration. The sort is stable, so
    rows within one provider keep the order they were captured in.
    """
    indexed = list(enumerate(entries))
    indexed.sort(key=lambda pair: (-source_rank(pair[1].get("source")), pair[0]))
    return [entry for _index, entry in indexed][: max_candidates()]


def primary_url(candidates: Any) -> Optional[str]:
    """The URL that goes in `cover_image_url` (denormalised first candidate)."""
    entries = normalise_candidates(candidates)
    return entries[0]["url"] if entries else None


def candidates_for(url: Optional[str], *, variant: Optional[str] = None) -> list[dict]:
    """A one-entry list, or [] - the shape every write path needs."""
    entry = make_candidate(url, variant=variant)
    return [entry] if entry else []


def _first_raw_url(candidates: Any) -> Optional[str]:
    """The first URL string in a raw candidate list, whatever shape it is in."""
    if isinstance(candidates, str):
        return candidates
    if isinstance(candidates, dict):
        value = candidates.get("url")
        return value if isinstance(value, str) else None
    if isinstance(candidates, list):
        for item in candidates:
            url = _first_raw_url(item)
            if url:
                return url
    return None


#: The four cover columns, as a single unit. Every write path produces them here.
COVER_COLUMNS: tuple[str, ...] = (
    "cover_image_url",
    "cover_candidates",
    "cover_status",
    "cover_source",
)


def cover_fields(
    url: Optional[str] = None,
    candidates: Any = None,
    *,
    variant: Optional[str] = None,
) -> dict:
    """The one way to compute the cover columns for a write.

    Ingestion, the repair script and any future admin endpoint used to compute
    these four values separately, and that is exactly how `uploads.mangadex.org`
    URLs kept being written after the host stopped serving images: each path made
    its own decision. The seam keeps them consistent by construction:

    * `cover_image_url` is always `cover_candidates[0]`, or None;
    * a blocked or non-https URL never becomes the primary;
    * `cover_status` follows the stored URL (`ok` for a host a browser can load,
      `dead` for one it cannot, `unverified` when there is nothing to judge).

    Returns a dict keyed by `COVER_COLUMNS`, ready for `Manga(**fields)` or
    `update(Manga).values(**fields)`.
    """
    entries = rank_candidates(normalise_candidates(candidates))
    if not entries:
        entries = candidates_for(url, variant=variant)

    if entries:
        primary = entries[0]["url"]
        status, source = classify_cover(primary)
    else:
        primary = None
        # Judge the URL that was offered even though it was dropped: a row whose only
        # cover is a blocked host is dead, not merely unverified - we know it cannot
        # render, and "unverified" would put it back in the retry queue forever.
        status, source = classify_cover(_first_raw_url(candidates) or url)
        if status == "ok":
            status = "unverified"

    return {
        "cover_image_url": primary,
        "cover_candidates": entries,
        "cover_status": status,
        "cover_source": source,
    }


def apply_cover_fields(target: Any, url: Optional[str] = None, candidates: Any = None) -> dict:
    """Set the four columns on an ORM object (or any attribute holder) at once."""
    fields = cover_fields(url, candidates)
    for name, value in fields.items():
        setattr(target, name, value)
    return fields


def public_cover(
    url: Optional[str] = None, candidates: Any = None
) -> tuple[Optional[str], list[dict]]:
    """The pair a response may hand to a browser: `(cover_image_url, candidates)`.

    Guarantees three properties at one place instead of at every call site:

    * no blocked host is ever emitted (a dead URL becomes `None`, not a broken
      `<img>`);
    * `cover_image_url` is exactly the first candidate, so clients that only read
      the legacy field still get the best URL;
    * a row written before the candidate column existed still yields one entry,
      derived from its URL, so the API is self-healing rather than empty;
    * the order is the *configured* provider order, not the order the row happened
      to be written with, so promoting a provider needs no backfill.

    Returns `(None, [])` when nothing safe exists - which the client renders as a
    tile without making a request.
    """
    entries = rank_candidates(normalise_candidates(candidates))
    if not entries:
        entries = candidates_for(url)
    return (entries[0]["url"] if entries else None), entries
