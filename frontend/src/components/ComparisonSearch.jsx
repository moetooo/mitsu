import { useState } from 'react';

const PRESET_COMPARISONS = [
  { ref: "Berserk", twist: "happier", label: "Like Berserk but happier" },
  { ref: "Naruto", twist: "darker and grittier", label: "Like Naruto but darker" },
  { ref: "Blue Period", twist: "with romance", label: "Like Blue Period with romance" },
  { ref: "Solo Leveling", twist: "with comedy & slice of life", label: "Like Solo Leveling with comedy" },
  { ref: "Death Note", twist: "sci-fi space opera", label: "Like Death Note in space" }
];

export default function ComparisonSearch({ onExecuteComparison, loading }) {
  const [baseManga, setBaseManga] = useState('');
  const [modifier, setModifier] = useState('');

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    if (!baseManga.trim()) return;
    
    const constructedQuery = `Like ${baseManga.trim()} but ${modifier.trim() || 'with unique twists'}`;
    onExecuteComparison(constructedQuery, baseManga, modifier);
  };

  const handlePreset = (p) => {
    setBaseManga(p.ref);
    setModifier(p.twist);
    onExecuteComparison(p.label, p.ref, p.twist);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6 bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] p-6 md:p-8 rounded-3xl shadow-xl">
      <div className="text-center space-y-2">
        <span className="px-3 py-1 bg-[var(--bg-color)] text-[var(--accent-vermillion)] border border-[var(--accent-vermillion)] text-xs font-serif-jp font-bold rounded-full uppercase tracking-wider">
          Hybrid Comparison Search
        </span>
        <h2 className="text-2xl md:text-3xl font-serif-jp font-bold text-[var(--text-color)]">
          Compare & Mix Manga Tropes
        </h2>
        <p className="text-xs md:text-sm text-[var(--text-muted)] font-serif-jp">
          Combine a foundational manga title with a specific atmospheric twist to discover matching stories.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-5 gap-3">
        <div className="md:col-span-2">
          <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1">
            Base Manga Title
          </label>
          <input
            type="text"
            value={baseManga}
            onChange={(e) => setBaseManga(e.target.value)}
            placeholder="e.g. Berserk, Naruto"
            className="w-full bg-[var(--bg-color)] border border-[var(--border-color)] rounded-xl px-4 py-2.5 text-xs font-serif-jp text-[var(--text-color)] focus:outline-none focus:border-[var(--accent-vermillion)]"
          />
        </div>

        <div className="md:col-span-2">
          <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1">
            Atmospheric Twist / Modifier
          </label>
          <input
            type="text"
            value={modifier}
            onChange={(e) => setModifier(e.target.value)}
            placeholder="e.g. happier, darker, romance"
            className="w-full bg-[var(--bg-color)] border border-[var(--border-color)] rounded-xl px-4 py-2.5 text-xs font-serif-jp text-[var(--text-color)] focus:outline-none focus:border-[var(--accent-vermillion)]"
          />
        </div>

        <div className="flex items-end">
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-[var(--accent-vermillion)] text-white font-serif-jp font-bold text-xs rounded-xl transition-all shadow-sm active:scale-95 disabled:opacity-50 cursor-pointer"
          >
            {loading ? 'Searching...' : 'Compare'}
          </button>
        </div>
      </form>

      {/* Preset Quick Chips */}
      <div className="space-y-2 pt-2 border-t border-[var(--border-color)]">
        <span className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
          Suggested Preset Comparisons
        </span>
        <div className="flex flex-wrap gap-2">
          {PRESET_COMPARISONS.map((p, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => handlePreset(p)}
              className="px-3 py-1.5 bg-[var(--bg-color)] hover:border-[var(--accent-vermillion)] border border-[var(--border-color)] rounded-full text-xs font-serif-jp text-[var(--text-color)] transition-all cursor-pointer flex items-center gap-1.5"
            >
              <span className="text-[var(--accent-vermillion)] text-xs">❖</span>
              {p.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
