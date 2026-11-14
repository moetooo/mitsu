// FE-28: HTML entities are decoded at one boundary.
//
// AniList descriptions arrive as HTML (`<br>`, `<i>`, `&quot;`, `&#39;`). The
// view stripped tags, then patched two entities by hand, so `&amp;` and `&nbsp;`
// still rendered literally and the same string looked different on the card, in
// the dossier and in the modal. The backend has the same gap (PIPE-14); until it
// decodes there, this is the single place the UI decodes.

const NAMED_ENTITIES = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
  nbsp: ' ',
  hellip: '…',
  mdash: '—',
  ndash: '–',
  lsquo: '‘',
  rsquo: '’',
  ldquo: '“',
  rdquo: '”',
  bull: '•',
  middot: '·',
  eacute: 'é',
  egrave: 'è',
  uuml: 'ü',
  ouml: 'ö',
  auml: 'ä',
  deg: '°'
};

export function decodeHtmlEntities(value) {
  if (typeof value !== 'string' || value.indexOf('&') === -1) return value;
  return value.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, body) => {
    if (body[0] === '#') {
      const code = body[1] === 'x' || body[1] === 'X'
        ? parseInt(body.slice(2), 16)
        : parseInt(body.slice(1), 10);
      if (!Number.isFinite(code) || code < 1 || code > 0x10ffff) return match;
      try {
        return String.fromCodePoint(code);
      } catch {
        return match;
      }
    }
    const named = NAMED_ENTITIES[body.toLowerCase()];
    return named === undefined ? match : named;
  });
}

const FALLBACK_SYNOPSIS = 'No synopsis description available for this title.';

// Strip tags, decode entities, collapse the whitespace the stripped tags leave
// behind. Order matters: decode after stripping, so a decoded `&lt;` is text and
// not a tag the strip pass would eat.
export function cleanSynopsis(value, fallback = FALLBACK_SYNOPSIS) {
  if (value === null || value === undefined) return fallback;
  const text = typeof value === 'string' ? value : String(value);
  const stripped = text.replace(/<[^>]*>?/g, ' ');
  const decoded = decodeHtmlEntities(stripped);
  const collapsed = decoded.replace(/\s+/g, ' ').trim();
  return collapsed === '' ? fallback : collapsed;
}
