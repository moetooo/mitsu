import { useState, useEffect } from 'react';

export default function Header({ 
  activeTab, 
  setActiveTab, 
  bookmarkCount, 
  onOpenSettings,
  theme = 'sumi'
}) {
  const [isVisible, setIsVisible] = useState(true);
  const [lastScrollY, setLastScrollY] = useState(0);

  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      
      // Auto-hide when scrolling down past 50px, reveal when scrolling up
      if (currentScrollY > lastScrollY && currentScrollY > 50) {
        setIsVisible(false);
      } else if (currentScrollY < lastScrollY) {
        setIsVisible(true);
      }
      
      setLastScrollY(currentScrollY);
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [lastScrollY]);

  return (
    <header className={`sticky top-0 z-40 bg-[var(--bg-color)]/90 backdrop-blur-md border-b border-[var(--border-color)] px-4 md:px-8 py-3.5 transition-all duration-300 ${isVisible ? 'translate-y-0' : '-translate-y-full'}`}>
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
            onClick={() => setActiveTab('trending')}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer ${
              activeTab === 'trending'
                ? 'bg-[var(--accent-vermillion)] text-white shadow-sm font-bold'
                : 'text-[var(--text-muted)] hover:text-[var(--text-color)]'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" />
            </svg>
            Trending
          </button>

          <button
            onClick={() => setActiveTab('surprise')}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer ${
              activeTab === 'surprise'
                ? 'bg-[var(--accent-vermillion)] text-white shadow-sm font-bold'
                : 'text-[var(--text-muted)] hover:text-[var(--text-color)]'
            }`}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
            </svg>
            Surprise Me
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
