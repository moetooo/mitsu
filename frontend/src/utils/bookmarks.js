// FE-18: what a saved title actually needs.
//
// Bookmarks were stored as the whole API result, so every save carried the
// pipeline fields (`llm_reasoning`, `inferred_tags`, `similarity_score`, …) and
// the list grew without a limit until the quota write started failing.
//
// The allowlist below is the union of the fields MangaCard and MangaDetailModal
// read, because a bookmark is rendered by the card and opened by the modal. A
// field added to either of them has to be added here, or it will look empty in
// the Saved tab only — which is why this list is commented rather than implicit.

export const MAX_BOOKMARKS = 150;

const CARD_AND_MODAL_FIELDS = [
  // identity
  'id',
  'anilist_id',
  'mal_id',
  // titles: `title` may be a string or an object, MangaCard handles both
  'title',
  'title_english',
  'title_romaji',
  // cover art
  'cover_image_url',
  'banner_image',
  // scores and dates
  'average_score',
  'score',
  'bayesian_rating',
  'start_year',
  'release_year',
  'status',
  'chapters',
  // people
  'author',
  'artist',
  'authors',
  'staff',
  // taxonomy
  'genres',
  'tags',
  'inferred_tags',
  // flags and prose
  'is_nsfw',
  'format_type',
  'synopsis',
  'llm_reasoning',
  // match score, shown as a pill on the card
  'similarity_score'
];

export function toBookmarkRecord(manga) {
  if (!manga || manga.id === null || manga.id === undefined) return null;
  const record = {};
  for (const field of CARD_AND_MODAL_FIELDS) {
    if (manga[field] !== undefined) record[field] = manga[field];
  }
  return record;
}

// Adds or removes one title, keeps the stored form minimal, and enforces the cap
// by dropping the oldest entries — a "Saved" tab the user has to clear by hand
// because the browser refused the write is worse than a bounded one.
export function toggleBookmark(list, manga) {
  const current = Array.isArray(list) ? list : [];
  if (!manga || manga.id === null || manga.id === undefined) return current;
  if (current.some(entry => entry && entry.id === manga.id)) {
    return current.filter(entry => !entry || entry.id !== manga.id);
  }
  const record = toBookmarkRecord(manga);
  if (!record) return current;
  const next = [...current, record];
  return next.length > MAX_BOOKMARKS ? next.slice(next.length - MAX_BOOKMARKS) : next;
}

// The persisted form of an in-memory list.
export function toStoredBookmarks(list) {
  const records = (Array.isArray(list) ? list : []).map(toBookmarkRecord).filter(Boolean);
  return records.length > MAX_BOOKMARKS ? records.slice(records.length - MAX_BOOKMARKS) : records;
}
