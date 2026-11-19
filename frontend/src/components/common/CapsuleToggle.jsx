/**
 * A capsule of mutually exclusive options, with one highlight that slides.
 *
 * This is the app's one toggle: the header's tab strip and the Trending rail's
 * format switch are the same control with different sizes, because "pick one of
 * a short list" should look and behave the same everywhere. Three settings define
 * a capsule, and nothing else does:
 *
 *   size   'sm' (rail, uppercase micro-labels) | 'md' (header tabs)
 *   accent 'vermillion' | 'indigo' | 'ink' — the highlight colour token
 *   active 'pressed' (state switch) | 'current' (navigation, `aria-current`)
 *
 * Behavioural rules, identical at every call site:
 * - the highlight is one element moved with `transform`, never a background on
 *   each button: the toggle reads as a position being carried from slot to slot;
 * - slots are equal width: the track is a grid of `1fr` columns sized to the
 *   widest label, which makes "one indicator width = one slot" true, so the
 *   highlight always lands inside the button it belongs to and no label is
 *   truncated to make the maths work;
 * - motion is 300ms ease-out and off entirely under `prefers-reduced-motion`;
 * - it never renders a link and never navigates: it reports the chosen id and
 *   leaves routing to the caller.
 */
const SIZES = {
  sm: {
    item: 'px-3 py-1 text-[11px] font-mono uppercase tracking-[0.12em]',
    indicator: 'inset-y-1 left-1'
  },
  md: {
    item: 'px-4 py-1.5 text-xs font-medium',
    indicator: 'inset-y-1 left-1'
  }
};

// One slot = (track width - 2 * p-1) / n. The track is a grid of equal columns
// sized to the widest label, so this width and a column are the same thing.
const slotWidth = (count) => `calc((100% - 0.5rem) / ${count})`;

const ACCENTS = {
  vermillion: { indicator: 'bg-[var(--accent-vermillion)]', badge: 'bg-[var(--accent-vermillion)]' },
  indigo: { indicator: 'bg-[var(--accent-indigo)]', badge: 'bg-[var(--accent-indigo)]' },
  ink: { indicator: 'bg-[var(--text-color)]', badge: 'bg-[var(--text-color)]' }
};

export default function CapsuleToggle({
  options = [],
  value,
  onChange,
  // The group's accessible name: "Trending format", "Primary", …
  label,
  size = 'sm',
  accent = 'vermillion',
  // Navigation uses `aria-current="page"`; a state switch uses `aria-pressed`.
  active = 'pressed',
  className = ''
}) {
  const sizing = SIZES[size] || SIZES.sm;
  const colours = ACCENTS[accent] || ACCENTS.vermillion;
  const index = Math.max(0, options.findIndex(option => option.id === value));

  return (
    <div
      role="group"
      aria-label={label}
      className={`relative inline-grid max-w-full grid-flow-col auto-cols-fr rounded-full border border-[var(--border-color)] bg-[var(--surface-color)] shadow-sm p-1 ${className}`}
    >
      <span
        aria-hidden="true"
        data-capsule-indicator=""
        className={`pointer-events-none absolute rounded-full shadow-xs transition-transform duration-300 ease-out motion-reduce:transition-none ${sizing.indicator} ${colours.indicator}`}
        style={{
          width: slotWidth(options.length),
          // Own-width steps line up with equal slots, so no measurement is needed
          // and the capsule keeps one size whichever option is selected.
          transform: `translateX(${index * 100}%)`
        }}
      />

      {options.map(option => {
        const selected = option.id === value;
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => onChange?.(option.id)}
            aria-pressed={active === 'pressed' ? selected : undefined}
            aria-current={active === 'current' && selected ? 'page' : undefined}
            className={`relative z-10 flex w-full items-center justify-center gap-1.5 rounded-full whitespace-nowrap transition-colors duration-200 cursor-pointer ${sizing.item} ${
              selected
                ? 'text-white font-bold'
                : 'text-[var(--text-muted)] hover:text-[var(--text-color)]'
            }`}
          >
            {option.icon ? <span className="shrink-0">{option.icon}</span> : null}
            <span>{option.label}</span>
            {option.badge ? (
              <span
                className={`ml-0.5 px-1.5 rounded-full text-[10px] font-bold text-white border border-[var(--bg-color)] ${colours.badge}`}
              >
                {option.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
