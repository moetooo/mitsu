import CapsuleToggle from '../common/CapsuleToggle';
import CoverRail from '../manga/CoverRail';
import { TRENDING_FORMATS, BOARD_SIZE } from '../../hooks/useTrendingBoard';

/**
 * The Trending section on Explore.
 *
 * A word, a hairline, a format toggle, and a rail of ten covers — no icon, no
 * grid, no rank numbers and no Load More. The toggle is local UI state: choosing
 * Manhwa changes what is in the rail, not where the user is, so no URL and no
 * history entry is involved.
 *
 * It renders nothing at all while there is nothing to show and nothing is
 * loading (empty or failed fetch): an empty "TRENDING" heading above no covers
 * would promise a section that is not there.
 */
export default function TrendingSection({
  items = [],
  loading = false,
  format = 'manga',
  onChangeFormat,
  onSelect
}) {
  if (!loading && items.length === 0) return null;

  return (
    <section aria-labelledby="trending-heading" className="space-y-4">
      <div>
        <h2
          id="trending-heading"
          className="font-heading text-sm font-bold uppercase tracking-[0.18em] text-[var(--text-muted)]"
        >
          Trending
        </h2>
        <div aria-hidden="true" className="mt-2 h-px w-full bg-[var(--border-color)]" />
      </div>

      {/* The same capsule the header's tabs use, one size smaller: a rail label
          should not compete with the page title. */}
      <CapsuleToggle
        className="mt-1"
        label="Trending format"
        size="sm"
        value={format}
        onChange={onChangeFormat}
        options={TRENDING_FORMATS.map(option => ({ id: option.format, label: option.label }))}
      />

      <CoverRail
        items={items}
        loading={loading}
        onSelect={onSelect}
        // No destination tile: the rail is the whole trending surface now.
        onAction={null}
        skeletonCount={BOARD_SIZE}
      />
    </section>
  );
}
