import { useState } from 'react';

export default function SettingsModal({ settings, setSettings, isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200">
      <div 
        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
        onClick={onClose}
      />
      
      <div className="relative bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] w-full max-w-lg rounded-3xl p-6 sm:p-8 shadow-2xl space-y-6 z-10 max-h-[90vh] overflow-y-auto custom-scrollbar">
        
        <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-[var(--hanko-bg)] border border-[var(--accent-vermillion)] flex items-center justify-center text-[var(--accent-vermillion)] font-serif-jp text-sm font-bold">
              ❖
            </div>
            <div>
              <h3 className="text-lg font-serif-jp font-bold text-[var(--text-color)]">Theme & Preferences</h3>
              <p className="text-xs text-[var(--text-muted)] font-mono">Aesthetic Themes & Security Controls</p>
            </div>
          </div>

          <button 
            onClick={onClose}
            className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] rounded-full hover:bg-[var(--bg-color)] transition-colors cursor-pointer"
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

          {/* Shibui Accent Color Palette Selector */}
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">
              Accent Color Palette (Shibui Styling)
            </label>
            <div className="grid grid-cols-5 gap-2">
              {[
                { id: 'vermillion', kanji: '朱', name: 'Vermillion', color: 'bg-[#c33d2e]' },
                { id: 'gold', kanji: '琥珀', name: 'Kintsugi', color: 'bg-[#d97706]' },
                { id: 'emerald', kanji: '竹', name: 'Emerald', color: 'bg-[#2e7d32]' },
                { id: 'indigo', kanji: '藍', name: 'Indigo', color: 'bg-[#4a69bd]' },
                { id: 'rose', kanji: '桜', name: 'Rose', color: 'bg-[#e11d48]' }
              ].map(a => (
                <button
                  key={a.id}
                  onClick={() => setSettings(prev => ({ ...prev, accent: a.id, hoverAccent: a.id }))}
                  className={`p-2.5 rounded-2xl border flex flex-col items-center gap-1 transition-all cursor-pointer text-center ${
                    (settings.accent || settings.hoverAccent || 'vermillion') === a.id
                      ? 'border-[var(--accent-vermillion)] bg-[var(--bg-color)] shadow-md ring-2 ring-[var(--accent-vermillion)]/30 text-[var(--text-color)] font-bold'
                      : 'border-[var(--border-color)] bg-[var(--bg-color)]/50 text-[var(--text-muted)] hover:border-[var(--accent-indigo)]'
                  }`}
                >
                  <div className={`w-4 h-4 rounded-full ${a.color} border border-white/20 shadow-xs mb-0.5`} />
                  <span className="text-[11px] font-serif-jp leading-none">{a.kanji}</span>
                  <span className="text-[9px] font-mono leading-none opacity-80">{a.name}</span>
                </button>
              ))}
            </div>
          </div>


          {/* Feature 32: NSFW / Mature Cover Blur Safety Toggle */}
          <div className="border border-[var(--border-color)] rounded-2xl p-4 bg-[var(--bg-color)]/50 flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-bold text-[var(--text-color)] uppercase">
                  🔞 NSFW Cover Blur Safety
                </span>
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--hanko-bg)] text-[var(--accent-vermillion)] font-mono font-bold">
                  Feature 32
                </span>
              </div>
              <p className="text-[11px] text-[var(--text-muted)] font-mono">
                Applies backdrop blur to mature/NSFW artwork until hovered over.
              </p>
            </div>

            <button
              type="button"
              onClick={() => setSettings(prev => ({ ...prev, nsfwBlur: !prev.nsfwBlur }))}
              className={`w-12 h-6 rounded-full p-1 transition-colors cursor-pointer border ${
                settings.nsfwBlur !== false
                  ? 'bg-[var(--accent-vermillion)] border-[var(--accent-vermillion)] justify-end'
                  : 'bg-[var(--surface-color)] border-[var(--border-color)] justify-start'
              } flex items-center`}
            >
              <div className="w-4 h-4 rounded-full bg-white shadow-xs transition-transform" />
            </button>
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

        </div>

      </div>
    </div>
  );
}
