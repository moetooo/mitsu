export default function Header({ 
  activeTab, 
  setActiveTab, 
  bookmarkCount, 
  onOpenSettings,
  theme = 'sumi'
}) {
  return (
    <header className="sticky top-0 z-40 bg-[var(--bg-color)]/90 backdrop-blur-md border-b border-[var(--border-color)] px-4 md:px-8 py-3.5 transition-colors duration-200">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
        
        {/* Logo */}
        <div 
          onClick={() => setActiveTab('explore')}
          className="flex items-center gap-3 cursor-pointer group"
        >
          <div className="w-8 h-8 rounded-lg bg-[var(--surface-color)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-vermillion)] font-bold text-sm shadow-sm group-hover:border-[var(--accent-vermillion)] transition-colors">
            ❖
          </div>
          <div className="flex flex-col">
            <span className="font-serif-jp text-lg md:text-xl font-bold tracking-tight text-[var(--text-color)] leading-tight">
              Mit<span className="text-[var(--accent-vermillion)]">su</span>
            </span>
            <span className="text-[9px] text-[var(--text-muted)] tracking-widest uppercase font-mono">
              AI Manga Discovery
            </span>
          </div>
        </div>

        {/* Navigation Tabs (Centered) */}
        <nav className="absolute left-1/2 -translate-x-1/2 flex items-center bg-[var(--surface-color)] border border-[var(--border-color)] rounded-full p-1 transition-colors shadow-sm">
          <button
            onClick={() => setActiveTab('explore')}
            className={`flex items-center gap-2 px-5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer ${
              activeTab === 'explore'
                ? 'bg-[var(--accent-vermillion)] text-white shadow-sm font-bold'
                : 'text-[var(--text-muted)] hover:text-[var(--text-color)]'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Explore
          </button>

          <button
            onClick={() => setActiveTab('bookmarks')}
            className={`flex items-center gap-2 px-5 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer relative ${
              activeTab === 'bookmarks'
                ? 'bg-[var(--accent-vermillion)] text-white shadow-sm font-bold'
                : 'text-[var(--text-muted)] hover:text-[var(--text-color)]'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill={activeTab === 'bookmarks' ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
            Saved
            {bookmarkCount > 0 && (
              <span className="ml-1 px-1.5 py-0.2 text-[10px] font-bold rounded-full bg-[var(--accent-vermillion)] text-white border border-[var(--bg-color)]">
                {bookmarkCount}
              </span>
            )}
          </button>
        </nav>

        {/* Settings Button */}
        <button
          onClick={onOpenSettings}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-color)] bg-[var(--surface-color)] border border-[var(--border-color)] rounded-full transition-all cursor-pointer hover:border-[var(--accent-indigo)]"
          title="Theme & UI Preferences"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>

      </div>
    </header>
  );
}
