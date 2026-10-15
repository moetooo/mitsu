/**
 * Category-Aware Tag Styling & Normalization Utilities
 * Formats inferred tags across Tropes, Relationships, Themes, Settings, and Demographics.
 */

export const CATEGORY_STYLES = {
  trope: {
    bg: 'bg-purple-500/10 dark:bg-purple-950/30',
    border: 'border-purple-500/30 dark:border-purple-500/40',
    text: 'text-purple-600 dark:text-purple-300',
    hover: 'hover:border-purple-500 hover:bg-purple-500/20',
    dot: 'bg-purple-400',
    label: 'Trope'
  },
  relationship: {
    bg: 'bg-rose-500/10 dark:bg-rose-950/30',
    border: 'border-rose-500/30 dark:border-rose-500/40',
    text: 'text-rose-600 dark:text-rose-300',
    hover: 'hover:border-rose-500 hover:bg-rose-500/20',
    dot: 'bg-rose-400',
    label: 'Dynamic'
  },
  theme: {
    bg: 'bg-emerald-500/10 dark:bg-emerald-950/30',
    border: 'border-emerald-500/30 dark:border-emerald-500/40',
    text: 'text-emerald-600 dark:text-emerald-300',
    hover: 'hover:border-emerald-500 hover:bg-emerald-500/20',
    dot: 'bg-emerald-400',
    label: 'Theme'
  },
  setting: {
    bg: 'bg-sky-500/10 dark:bg-sky-950/30',
    border: 'border-sky-500/30 dark:border-sky-500/40',
    text: 'text-sky-600 dark:text-sky-300',
    hover: 'hover:border-sky-500 hover:bg-sky-500/20',
    dot: 'bg-sky-400',
    label: 'Setting'
  },
  demographic: {
    bg: 'bg-amber-500/10 dark:bg-amber-950/30',
    border: 'border-amber-500/30 dark:border-amber-500/40',
    text: 'text-amber-600 dark:text-amber-300',
    hover: 'hover:border-amber-500 hover:bg-amber-500/20',
    dot: 'bg-amber-400',
    label: 'Demographic'
  },
  format: {
    bg: 'bg-teal-500/10 dark:bg-teal-950/30',
    border: 'border-teal-500/30 dark:border-teal-500/40',
    text: 'text-teal-600 dark:text-teal-300',
    hover: 'hover:border-teal-500 hover:bg-teal-500/20',
    dot: 'bg-teal-400',
    label: 'Format'
  },
  genre: {
    bg: 'bg-indigo-500/10 dark:bg-indigo-950/30',
    border: 'border-indigo-500/30 dark:border-indigo-500/40',
    text: 'text-[var(--accent-indigo)]',
    hover: 'hover:border-[var(--accent-indigo)] hover:bg-indigo-500/20',
    dot: 'bg-indigo-400',
    label: 'Genre'
  }
};

export function normalizeTag(tag) {
  if (!tag) return null;
  if (typeof tag === 'string') {
    return {
      slug: tag.toLowerCase().replace(/\s+/g, '_'),
      name: tag,
      category: 'genre',
      confidence: 1.0,
      provenance: 'raw'
    };
  }
  return {
    slug: tag.slug || tag.name?.toLowerCase().replace(/\s+/g, '_') || '',
    name: tag.name || tag.slug || '',
    category: (tag.category || 'genre').toLowerCase(),
    confidence: typeof tag.confidence === 'number' ? tag.confidence : 1.0,
    provenance: tag.provenance || 'ai'
  };
}

export function getTagStyle(category) {
  const cat = (category || 'genre').toLowerCase();
  return CATEGORY_STYLES[cat] || CATEGORY_STYLES.genre;
}
