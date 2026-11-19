/**
 * Surprise Me card layout + typography.
 *
 * This is the one place to edit the card's furniture and its text. Values are
 * plain numbers so tuning needs no CSS knowledge; the component reads them and
 * applies them inline / as custom properties.
 *
 * Covered by tests in `SurpriseView.test.jsx` (the rendered styles must come
 * from these values, so editing them really moves the card).
 */
/* ── Surprise Me card: manual layout values ────────────────────────────────
   Change these numbers to move the card furniture. Everything is in pixels
   unless the name says otherwise, and nothing else in the file hardcodes the
   same spacing, so this block is the only place to edit.

   PLATE_BOTTOM       space under the title / genre / year block. Smaller value
                      places the text lower on the card; increase it to lift the
                      text block up from the bottom edge (0 = flush).
   PLATE_SIDE         left/right inset of the text block.
   PLATE_TOP          space above the title inside the block.
   SECTION_GAP        vertical gap between stacked pieces of the hover reveal.
   EXPANDED_DROP      px the title / genre / year block sits lower once the peek
                      is open (hover or tap). This is a position, not a lift:
                      the block still follows the expansion, it just settles
                      this much closer to the card's bottom edge.

   The height of the whole bottom sheet is separate: it is the cover length
   setting (`imageLength`, 50-70 in Settings), not these values. */
export const SURPRISE_CARD_LAYOUT = {
  PLATE_BOTTOM: 12,
  PLATE_SIDE: 20,
  PLATE_TOP: 2,
  SECTION_GAP: 10,
  EXPANDED_DROP: 2
};

/* ── Surprise Me card: manual text values ──────────────────────────────────
   Every number that shapes the title, the "Genre • Year" line and the genre
   pills. Sizes are px, weight is a CSS font-weight, tracking is in em (negative
   tightens), lines is how many lines the title may wrap to before it ellipsises.

   These are applied as CSS variables on the card, so the responsive rule in
   index.css (`.surprise-card-title` at >=640px uses the DESKTOP size) keeps
   working. Change a value here and the card follows; nothing else hardcodes
   these sizes. */
export const SURPRISE_CARD_TEXT = {
  // Placement of the whole title / genre / year block, in px from where the
  // layout puts it. Positive = down, negative = up. Position only: it does not
  // touch the cover, the scrim, the sheet height or the hover reveal.
  //   TEXT_OFFSET_Y        the resting position
  //   TEXT_OFFSET_Y_HOVER  the position after hover / expand
  TEXT_OFFSET_Y: 0,
  // The second position, used while hovered or while the peek is expanded.
  // Both are plain positions: switching between them is instant, no animation.
  TEXT_OFFSET_Y_HOVER: 8,

  // Title
  TITLE_SIZE_MOBILE: 16,
  TITLE_SIZE_DESKTOP: 18, // used from 640px up
  TITLE_WEIGHT: 700,
  TITLE_LINE_HEIGHT: 1.375,
  TITLE_TRACKING_EM: -0.01,
  TITLE_LINES: 1, // 1 = one line + ellipsis, 2 = two lines before ellipsis

  // "Genre • Year" line under the title
  META_SIZE: 11,
  META_WEIGHT: 400,
  META_LINE_HEIGHT: 1.4,
  META_TRACKING_EM: 0,
  META_OFFSET_Y: 2, // px; push the line down, negative pulls it into the title

  // Genre pills in the hover reveal
  PILL_SIZE: 9,

  // Status pill at the top-left of the card ("MANGA • ONGOING")
  STATUS_SIZE: 9,        // font size in px
  STATUS_WEIGHT: 400,    // 400 normal, 700 bold
  STATUS_TRACKING_EM: 0.1, // letter spacing, wide caps look (0.1 = widest)
  STATUS_PAD_X: 12,      // left/right padding in px
  STATUS_PAD_Y: 4,       // top/bottom padding in px
  STATUS_RADIUS: 9999,   // px; 9999 = pill, 12 = rounded rectangle

  // Synopsis excerpt shown in the hover reveal
  SYNOPSIS_SIZE: 12,       // font size in px
  SYNOPSIS_LINE_HEIGHT: 1.625, // line spacing multiplier
  SYNOPSIS_LINES_MOBILE: 2,    // lines before "…" below 640px
  SYNOPSIS_LINES_DESKTOP: 3,   // lines before "…" from 640px up

  // "Full Details" button in the hover reveal
  BUTTON_SIZE: 12,        // label font size in px
  BUTTON_WEIGHT: 700,     // 400 normal, 700 bold
  BUTTON_TRACKING_EM: 0.05, // letter spacing (0.05 = wide)
  BUTTON_PAD_Y: 10,       // top/bottom padding in px
  BUTTON_RADIUS: 9999     // px; 9999 = pill, 12 = rounded rectangle
};
