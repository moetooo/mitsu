// Primitives for the compact filter drawer. Kept out of FilterDrawer.jsx so the
// drawer file stays about filter state, not chrome geometry.
//
// The panel owns its own scale (see --panel-* in index.css) so the four cards read
// as one instrument -- but every value is a theme token, so the light theme renders light
// cards and amoled renders true black instead of a dark island in a light page.

const SURFACE = 'var(--panel-bg)';
const CARD = 'var(--panel-card)';
const HAIRLINE = 'var(--panel-border)';
const HAIRLINE_HOVER = 'var(--panel-border-hover)';
const CRIMSON = 'var(--panel-accent)';
const IDLE = 'var(--text-muted)';
const TRACK = 'var(--panel-track)';
const TRACK_BORDER = 'var(--panel-track-border)';

/**
 * One filter card: 6px state dot, 10px tracked monospace title, a crimson badge
 * carrying the value, and a Clear button that only exists once the card differs
 * from its default.
 */
export function FilterCard({ title, badge, active = false, onClear, children }) {
  return (
    <div
      className="flex flex-col gap-1.5 rounded-lg border px-3 py-2 transition-colors min-w-0"
      style={{ background: CARD, borderColor: HAIRLINE }}
      onMouseEnter={event => {
        event.currentTarget.style.borderColor = HAIRLINE_HOVER;
      }}
      onMouseLeave={event => {
        event.currentTarget.style.borderColor = HAIRLINE;
      }}
    >
      <div className="flex items-center justify-between gap-1.5 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            aria-hidden="true"
            className="shrink-0 rounded-full"
            style={{
              width: 6,
              height: 6,
              background: active ? CRIMSON : IDLE,
              boxShadow: active ? `0 0 6px color-mix(in srgb, ${CRIMSON} 70%, transparent)` : 'none'
            }}
          />
          <span
            className="font-mono uppercase tracking-[0.08em] text-[10px] truncate"
            style={{ color: 'var(--text-muted)' }}
          >
            {title}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <span
            className="rounded font-mono font-bold text-[9px] px-1.5 py-0.5 border tabular-nums"
            style={{
              background: `color-mix(in srgb, ${CRIMSON} 10%, transparent)`,
              borderColor: `color-mix(in srgb, ${CRIMSON} 25%, transparent)`,
              color: CRIMSON
            }}
          >
            {badge}
          </span>
          {onClear && (
            <button
              type="button"
              onClick={onClear}
              aria-label={`Clear ${title}`}
              className="font-mono text-[9px] px-1 rounded transition-colors cursor-pointer"
              style={{ color: IDLE }}
              onMouseEnter={event => {
                event.currentTarget.style.color = CRIMSON;
              }}
              onMouseLeave={event => {
                event.currentTarget.style.color = IDLE;
              }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {children}
    </div>
  );
}

/**
 * Full-width segmented bar. One track, equal cells, no pill gaps: the selected
 * cell fills crimson so the bar reads as a switch rather than a list of buttons.
 */
export function Segmented({ options, isActive, onSelect, wide = false, ariaLabel }) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={`grid gap-1 p-0.5 rounded-md border ${wide ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-4'}`}
      style={{
        background: `color-mix(in srgb, ${TRACK} 80%, transparent)`,
        borderColor: TRACK_BORDER
      }}
    >
      {options.map(option => {
        const active = isActive(option);
        return (
          <button
            key={option.id ?? option.label}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(option)}
            className="py-1 px-1.5 rounded font-mono text-[9px] leading-4 truncate transition-all cursor-pointer"
            style={
              active
                ? {
                    background: CRIMSON,
                    color: '#fff',
                    fontWeight: 700,
                    boxShadow: `0 0 8px color-mix(in srgb, ${CRIMSON} 45%, transparent)`
                  }
                : { color: IDLE }
            }
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function Track({ children }) {
  return <div className="compact-range relative h-4 w-full flex items-center">{children}</div>;
}

/** The clickable scale under a slider: 9px monospace, one button per stop. */
export function Ticks({ stops, activeIndex, onPick }) {
  return (
    <div className="flex justify-between -mt-0.5">
      {stops.map((stop, index) => (
        <button
          key={stop.label}
          type="button"
          onClick={() => onPick(index)}
          className="font-mono text-[9px] px-0.5 transition-colors cursor-pointer tabular-nums"
          style={{ color: index === activeIndex ? CRIMSON : IDLE }}
        >
          {stop.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Left-anchored single thumb over discrete stops. The native input keeps ARIA and
 * keyboard semantics and snaps to an index; the visual thumb comes from the
 * `.compact-range` rules, so the drag-only glow is the same one the year slider
 * uses.
 */
export function StopsSlider({ stops, index, onChange, ariaLabel, activeIndex }) {
  const last = stops.length - 1;
  const percent = (index / last) * 100;

  return (
    <Track>
      <div
        className="absolute inset-x-0 rounded-full"
        style={{ height: 3.5, background: TRACK_BORDER }}
      />
      <div
        className="absolute rounded-full"
        style={{ height: 3.5, left: 0, width: `${percent}%`, background: CRIMSON }}
      />
      <input
        type="range"
        min={0}
        max={last}
        step={1}
        value={index}
        aria-label={ariaLabel}
        onChange={event => onChange(Number(event.target.value))}
      />
      <span className="sr-only">{stops[activeIndex ?? index]?.label}</span>
    </Track>
  );
}

/**
 * Dual-thumb year range. Two native inputs share the track so each thumb keeps its
 * own keyboard handling; values are clamped here so the thumbs cannot cross, which
 * is the only invariant the API cares about (min <= max).
 */
export function DualRange({ low, high, min, max, step, onLow, onHigh, lowLabel, highLabel, ariaLabel }) {
  const percent = value => ((value - min) / (max - min)) * 100;
  const left = Math.min(percent(low), percent(high));
  const width = Math.max(0, Math.abs(percent(high) - percent(low)));

  return (
    <Track aria-label={ariaLabel}>
      <div
        className="absolute inset-x-0 rounded-full"
        style={{ height: 3.5, background: TRACK_BORDER }}
      />
      <div
        className="absolute rounded-full"
        style={{ height: 3.5, left: `${left}%`, width: `${width}%`, background: CRIMSON }}
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={low}
        aria-label={lowLabel}
        onChange={event => onLow(Math.min(Number(event.target.value), high))}
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={high}
        aria-label={highLabel}
        onChange={event => onHigh(Math.max(Number(event.target.value), low))}
      />
    </Track>
  );
}

/** One removable "this is staged" chip in the footer summary. */
export function StagedChip({ label, onRemove, muted = false }) {
  return (
    <span
      className={`inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-full border text-[10px] font-mono whitespace-nowrap ${
        muted
          ? 'border-[var(--border-color)] text-[var(--text-muted)] bg-[var(--bg-color)]/60 line-through'
          : 'border-[var(--panel-accent)]/50 text-[var(--panel-accent)] bg-[var(--panel-accent)]/12'
      }`}
    >
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter ${label}`}
        className="w-4 h-4 rounded-full flex items-center justify-center hover:bg-[var(--panel-accent)] hover:text-white transition-colors cursor-pointer"
      >
        ×
      </button>
    </span>
  );
}

/** Pill used by the tag groups. */
export function Pill({ active, excluded, onClick, title, children, className = '' }) {
  const tone = active
    ? 'bg-[var(--panel-accent)] border-[var(--panel-accent)] text-white font-bold shadow-[0_0_10px_color-mix(in_srgb,var(--panel-accent)_35%,transparent)]'
    : excluded
      ? 'bg-[var(--bg-color)] border-[var(--panel-accent)]/70 text-[var(--text-muted)] line-through'
      : 'bg-[var(--surface-color)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)] hover:border-[var(--text-muted)]';

  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`rounded-full border transition-all cursor-pointer select-none ${tone} ${className}`}
    >
      {children}
    </button>
  );
}

export { SURFACE, CARD, HAIRLINE, CRIMSON, IDLE };
