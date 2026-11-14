// One score conversion for the whole UI (FE-14).
//
// The catalogue stores `average_score` on MAL's 0-100 scale, but roulette rows
// and some provider payloads arrive on a 0-10 scale, so each component used to
// guess independently -- the detail modal divided by 10 unconditionally (a 0-10
// value rendered as 0.8), the Surprise dossier guessed with `> 10`, and the
// Hero banner always divided. Keeping the guess in one place means a new
// surface cannot drift.
export function scoreOutOfTen(value) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return numeric > 10 ? numeric / 10 : numeric;
}

// Returns a display string, or null when there is no score to show.
export function formatScore(value, digits = 1) {
  const score = scoreOutOfTen(value);
  return score === null ? null : score.toFixed(digits);
}
