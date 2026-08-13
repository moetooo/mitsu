export default function SettingsModal({ settings, setSettings, isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200">
      <div 
        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
        onClick={onClose}
      />
      
      <div className="relative bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] w-full max-w-lg rounded-3xl p-6 sm:p-8 shadow-2xl space-y-6 z-10 animate-in zoom-in-95 duration-200">
        
        <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-[var(--hanko-bg)] border border-[var(--accent-vermillion)] flex items-center justify-center text-[var(--accent-vermillion)] font-serif-jp text-sm font-bold">
              ❖
            </div>
            <div>
              <h3 className="text-lg font-serif-jp font-bold text-[var(--text-color)]">Theme & Preferences</h3>
              <p className="text-xs text-[var(--text-muted)] font-mono">Aesthetic Themes & Grid Layout Settings</p>
            </div>
          </div>

          <button 
            onClick={onClose}
            className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] rounded-full hover:bg-[var(--bg-color)] transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-6">
          
          {/* Japanese Aesthetic Theme Token Selector */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
              Aesthetic Theme
            </label>
            <div className="grid grid-cols-3 gap-3">
              {[
                { id: 'sumi', name: 'Sumi (Dark Ink)', desc: 'Indigo Ink Theme', color: 'bg-[#12151d] border-[#5a71a0]' },
                { id: 'washi', name: 'Washi (Paper Light)', desc: 'Warm Paper Theme', color: 'bg-[#f6f3eb] border-[#2a3a5c]' },
                { id: 'amoled', name: 'AMOLED Black', desc: 'True Pitch Black', color: 'bg-[#000000] border-[#ff3b30]' }
              ].map(t => (
                <button
                  key={t.id}
                  onClick={() => setSettings(prev => ({ ...prev, theme: t.id }))}
                  className={`p-3 rounded-2xl border flex flex-col items-start gap-1 transition-all cursor-pointer text-left ${
                    settings.theme === t.id
                      ? 'border-[var(--accent-vermillion)] bg-[var(--bg-color)] shadow-md ring-2 ring-[var(--accent-vermillion)]/30'
                      : 'border-[var(--border-color)] bg-[var(--bg-color)]/50 hover:border-[var(--accent-indigo)]'
                  }`}
                >
                  <div className={`w-full h-3 rounded-full ${t.color} border mb-1`} />
                  <span className="text-xs font-serif-jp font-bold text-[var(--text-color)]">{t.name}</span>
                  <span className="text-[10px] text-[var(--text-muted)] font-mono">{t.desc}</span>
                </button>
              ))}
            </div>
          </div>


          {/* Title Font Selector */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
              Title Font Style
            </label>
            <div className="grid grid-cols-4 gap-2">
              {[
                { id: 'serif', name: 'Mincho Serif' },
                { id: 'sans', name: 'Clean Sans' },
                { id: 'mono', name: 'Tech Mono' },
                { id: 'display', name: 'Cinematic' }
              ].map(f => (
                <button
                  key={f.id}
                  onClick={() => setSettings(prev => ({ ...prev, fontStyle: f.id }))}
                  className={`p-2.5 rounded-xl border text-center transition-all cursor-pointer font-mono text-xs ${
                    (settings.fontStyle || 'serif') === f.id
                      ? 'border-[var(--accent-vermillion)] bg-[var(--accent-vermillion)] text-white font-bold shadow-sm'
                      : 'border-[var(--border-color)] bg-[var(--bg-color)]/50 text-[var(--text-muted)] hover:text-[var(--text-color)]'
                  }`}
                >
                  {f.name}
                </button>
              ))}
            </div>
          </div>



          {/* Foldable Tweaks & Fine-Tuning Section */}
          <details className="group border border-[var(--border-color)] rounded-2xl p-3.5 bg-[var(--bg-color)]/40 transition-all">
            <summary className="text-xs font-mono font-bold text-[var(--text-muted)] group-hover:text-[var(--text-color)] uppercase tracking-wider cursor-pointer select-none flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 inline text-[var(--accent-vermillion)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Tweaks & Fine-Tuning
              </span>
              <span className="text-[10px] transition-transform group-open:rotate-180">▼</span>
            </summary>
            
            <div className="pt-4 space-y-4">
              {/* Card Hover Accent Color Selector */}
              <div>
                <label className="text-[11px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
                  Card Hover Accent Color
                </label>
                <div className="grid grid-cols-5 gap-2">
                  {[
                    { id: 'vermillion', name: 'Vermillion', color: 'bg-[#c33d2e]' },
                    { id: 'gold', name: 'Kintsugi Gold', color: 'bg-[#e6a15c]' },
                    { id: 'emerald', name: 'Jade Emerald', color: 'bg-[#4e9f78]' },
                    { id: 'mono', name: 'Sumi Charcoal', color: 'bg-[#555566]' },
                    { id: 'indigo', name: 'Classic Indigo', color: 'bg-[#5a71a0]' }
                  ].map(h => (
                    <button
                      key={h.id}
                      onClick={() => setSettings(prev => ({ ...prev, hoverAccent: h.id }))}
                      className={`p-2 rounded-xl border flex flex-col items-center gap-1.5 transition-all cursor-pointer ${
                        (settings.hoverAccent || 'vermillion') === h.id
                          ? 'border-[var(--accent-vermillion)] bg-[var(--surface-hover)] font-bold text-[var(--text-color)] shadow-sm ring-1 ring-[var(--accent-vermillion)]'
                          : 'border-[var(--border-color)] bg-[var(--bg-color)]/50 text-[var(--text-muted)] hover:text-[var(--text-color)]'
                      }`}
                    >
                      <div className={`w-3.5 h-3.5 rounded-full ${h.color}`} />
                      <span className="text-[10px] font-mono leading-none">{h.name}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Search Focus Style Selector */}
              <div>
                <label className="text-[11px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
                  Search Input Active Border Style
                </label>
                <div className="grid grid-cols-4 gap-2">
                  {[
                    { id: 'glow', name: 'Halo Glow' },
                    { id: 'vermillion', name: 'Solid Red' },
                    { id: 'subtle', name: 'Subtle Dark' },
                    { id: 'none', name: 'Borderless' }
                  ].map(st => (
                    <button
                      key={st.id}
                      onClick={() => setSettings(prev => ({ ...prev, focusStyle: st.id }))}
                      className={`p-2 rounded-xl border text-center transition-all cursor-pointer font-mono text-[11px] ${
                        (settings.focusStyle || 'glow') === st.id
                          ? 'border-[var(--accent-vermillion)] bg-[var(--accent-vermillion)] text-white font-bold shadow-sm'
                          : 'border-[var(--border-color)] bg-[var(--bg-color)]/50 text-[var(--text-muted)] hover:text-[var(--text-color)]'
                      }`}
                    >
                      {st.name}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </details>


          {/* Grid Size */}

          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
              Grid Card Density
            </label>
            <div className="grid grid-cols-3 gap-3">
              {[
                { id: 'compact', name: 'Compact' },
                { id: 'standard', name: 'Standard' },
                { id: 'large', name: 'Large' }
              ].map(g => (
                <button
                  key={g.id}
                  onClick={() => setSettings(prev => ({ ...prev, gridSize: g.id }))}
                  className={`p-2.5 rounded-xl border text-xs font-serif-jp transition-all cursor-pointer ${
                    settings.gridSize === g.id
                      ? 'border-[var(--accent-vermillion)] bg-[var(--accent-vermillion)] text-white font-bold'
                      : 'border-[var(--border-color)] bg-[var(--bg-color)] text-[var(--text-color)]'
                  }`}
                >
                  {g.name}
                </button>
              ))}
            </div>
          </div>


          {/* Limit */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
              Items Per Search
            </label>
            <div className="flex gap-2">
              {[8, 12, 16, 24].map(n => (
                <button
                  key={n}
                  onClick={() => setSettings(prev => ({ ...prev, limit: n }))}
                  className={`flex-1 py-2 rounded-xl text-xs font-mono border transition-all cursor-pointer ${
                    settings.limit === n
                      ? 'border-[var(--accent-vermillion)] bg-[var(--accent-vermillion)] text-white font-bold'
                      : 'border-[var(--border-color)] bg-[var(--bg-color)] text-[var(--text-color)]'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
