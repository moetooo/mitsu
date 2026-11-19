import useScrollLock from '../../hooks/useScrollLock';

export default function SettingsModal({ settings, setSettings, isOpen, onClose }) {
  // FE-13: the same counted lock as the detail modal. This used to be a private
  // copy of the effect; two overlays each saving/restoring their own value meant
  // whichever closed last decided the page overflow.
  useScrollLock(Boolean(isOpen));

  if (!isOpen) return null;

  const coverLength = Number.isFinite(settings.surpriseImageLength)
    ? Math.min(70, Math.max(50, settings.surpriseImageLength))
    : 60;
  // 50-70 is the band this control exposes; clamp so a value saved by an older
  // build cannot push the thumb (or the track fill) outside the track.
  const coverLengthPct = ((coverLength - 50) / 20) * 100;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200">
      <div 
        className="absolute inset-0 bg-black/80 transition-opacity"
        onClick={onClose}
      />
      
      <div 
        className="relative bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] w-full max-w-lg rounded-3xl shadow-2xl z-10 max-h-[85vh] flex flex-col overflow-hidden"
      >
        
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border-color)] px-6 pt-6 pb-4 sm:px-8 sm:pt-8 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-[var(--seal-bg)] border border-[var(--accent-vermillion)] flex items-center justify-center text-[var(--accent-vermillion)] font-heading text-sm font-bold">
              ❖
            </div>
            <div>
              <h3 className="text-lg font-heading font-bold text-[var(--text-color)]">Theme & Preferences</h3>
              <p className="text-xs text-[var(--text-muted)] font-mono">Aesthetic Themes & Security Controls</p>
            </div>
          </div>

          <button 
            onClick={onClose}
            className="icon-button-accent p-1.5 rounded-full text-[var(--text-muted)] hover:text-[var(--text-color)] cursor-pointer"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="panel-scroll custom-scrollbar px-6 pt-4 pb-6 sm:px-8 sm:pb-8">
        <div className="space-y-4">
          
          {/* Aesthetic Theme Token Selector */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1.5">
              Aesthetic Theme
            </label>
            <div className="grid grid-cols-2 gap-1.5">
              {[
                { id: 'washi', name: 'Paper Light' },
                { id: 'amoled', name: 'AMOLED Black' }
              ].map(t => (
                <button
                  key={t.id}
                  onClick={() => setSettings(prev => ({ ...prev, theme: t.id }))}
                  aria-pressed={settings.theme === t.id}
                  className="option-tile text-center font-heading cursor-pointer"
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>

          {/* Content Preferences & Safety Controls */}
          <div className="option-group space-y-3">
            <label className="text-[10px] font-mono font-bold text-[var(--accent-vermillion)] uppercase tracking-wider block">
              Content Preferences & Security
            </label>

            {/* Toggle 1: Include 18+ Titles */}
            <div className="flex items-center justify-between pt-1">
              <div className="space-y-0.5">
                <span className="text-xs font-mono font-bold text-[var(--text-color)] uppercase block">
                  Allow Explicit 18+ Titles
                </span>
                <p className="text-[10px] text-[var(--text-muted)] font-mono">
                  Include 18+ adult titles in search & recommendation results.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSettings(prev => ({ ...prev, allowNsfw: !prev.allowNsfw }))}
                className={`option-switch w-11 h-6 rounded-full p-1 cursor-pointer border ${
                  settings.allowNsfw
                    ? 'bg-[var(--accent-vermillion)]/15 border-[var(--accent-vermillion)] justify-end'
                    : 'bg-[var(--surface-color)] border-[var(--border-color)] justify-start'
                } flex items-center shrink-0`}
              >
                <div className="w-4 h-4 rounded-full bg-[var(--accent-vermillion)] shadow-xs" />
              </button>
            </div>

            <div className="border-t border-[var(--border-color)]/50 pt-2.5 flex items-center justify-between">
              <div className="space-y-0.5">
                <span className="text-xs font-mono font-bold text-[var(--text-color)] uppercase block">
                  Blur Explicit Cover Images
                </span>
                <p className="text-[10px] text-[var(--text-muted)] font-mono">
                  Applies backdrop blur to 18+ artwork until hovered over.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSettings(prev => ({ ...prev, nsfwBlur: !prev.nsfwBlur }))}
                className={`option-switch w-11 h-6 rounded-full p-1 cursor-pointer border ${
                  settings.nsfwBlur !== false
                    ? 'bg-[var(--accent-vermillion)]/15 border-[var(--accent-vermillion)] justify-end'
                    : 'bg-[var(--surface-color)] border-[var(--border-color)] justify-start'
                } flex items-center shrink-0`}
              >
                <div className="w-4 h-4 rounded-full bg-[var(--accent-vermillion)] shadow-xs" />
              </button>
            </div>
          </div>




          {/* Title Font Selector */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1.5">
              Title Font Style
            </label>
            <div className="grid grid-cols-4 gap-1.5">
              {[
                { id: 'serif', name: 'Editorial Serif' },
                { id: 'sans', name: 'Clean Sans' },
                { id: 'mono', name: 'Tech Mono' },
                { id: 'display', name: 'Cinematic' }
              ].map(f => (
                <button
                  key={f.id}
                  onClick={() => setSettings(prev => ({ ...prev, fontStyle: f.id }))}
                  aria-pressed={(settings.fontStyle || 'serif') === f.id}
                  className="option-tile text-center cursor-pointer font-mono"
                >
                  {f.name}
                </button>
              ))}
            </div>
          </div>


          {/* Grid Size */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1.5">
              Grid Card Density
            </label>
            <div className="grid grid-cols-3 gap-1.5">
              {[
                { id: 'compact', name: 'Compact' },
                { id: 'standard', name: 'Standard' },
                { id: 'large', name: 'Large' }
              ].map(g => (
                <button
                  key={g.id}
                  onClick={() => setSettings(prev => ({ ...prev, gridSize: g.id }))}
                  aria-pressed={settings.gridSize === g.id}
                  className="option-tile font-heading cursor-pointer"
                >
                  {g.name}
                </button>
              ))}
            </div>
          </div>

          {/* User Request: Surprise Me Discovery Card Cover Length Setting */}
          <div className="option-group space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-mono font-bold text-[var(--accent-vermillion)] uppercase tracking-wider">
                Surprise Me Cover Length
              </label>
              <span className="text-xs font-mono text-[var(--accent-vermillion)] font-bold px-2 py-0.5 rounded-md bg-[var(--surface-color)] border border-[var(--border-color)]">
                {coverLength}%
              </span>
            </div>
            <p className="text-[10px] text-[var(--text-muted)] font-mono">
              Adjust manga cover length proportion inside the Surprise Me card (50% to 70%, 60% default).
            </p>
            <div className="flex items-center gap-3">
              <span className="text-[10px] font-mono text-[var(--text-muted)]">50%</span>
              <input 
                type="range" 
                min="50" 
                max="70" 
                value={coverLength}
                step="1"
                aria-label="Surprise Me cover length"
                onChange={(e) => setSettings(prev => ({ ...prev, surpriseImageLength: parseInt(e.target.value, 10) }))}
                className="settings-range"
                style={{ '--range-pct': `${coverLengthPct}%` }}
              />
              <span className="text-[10px] font-mono text-[var(--text-muted)]">70% (Max)</span>
            </div>
            <div className="grid grid-cols-4 gap-2 pt-1">
              {[55, 60, 65, 70].map(val => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setSettings(prev => ({ ...prev, surpriseImageLength: val }))}
                  aria-pressed={coverLength === val}
                  className="option-tile font-mono cursor-pointer"
                >
                  {val}% {val === 60 ? '★' : ''}
                </button>
              ))}
            </div>
          </div>

        </div>
        </div>

      </div>
    </div>
  );
}
