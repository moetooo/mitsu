import { useState, useEffect, useRef } from 'react';
import CapsuleToggle from '../common/CapsuleToggle';

export default function Header({ 
  activeTab, 
  setActiveTab, 
  onSelectTab,
  bookmarkCount,
  onOpenSettings,
  onHome
}) {
  const [isVisible, setIsVisible] = useState(true);
  // FE-19: the last position lived in state, so it was a dependency of the
  // effect that registered the listener -- every scroll event tore the listener
  // down and added it again. A ref keeps the effect mounted once.
  const lastScrollYRef = useRef(0);

  const handleTab = (tab) => {
    if (onSelectTab) {
      onSelectTab(tab);
    } else if (setActiveTab) {
      setActiveTab(tab);
    }
  };

  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      const lastScrollY = lastScrollYRef.current;

      // Auto-hide when scrolling down past 50px, reveal when scrolling up
      if (currentScrollY > lastScrollY && currentScrollY > 50) {
        setIsVisible(false);
      } else if (currentScrollY < lastScrollY) {
        setIsVisible(true);
      }

      lastScrollYRef.current = currentScrollY;
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <header className={`sticky top-0 z-40 bg-[var(--bg-color)]/90 backdrop-blur-md border-b border-[var(--border-color)] px-4 md:px-8 py-3.5 transition-all duration-300 ${isVisible ? 'translate-y-0' : '-translate-y-full'}`}>
      {/* Three columns, and only the middle one is truly centred: the logo and the
          settings button get identical flexible space, so the tab capsule sits on
          the header's centre line instead of being pushed right by a wide logo. */}
      <div className="max-w-7xl mx-auto grid grid-cols-[1fr_auto_1fr] items-center gap-2 sm:gap-4">
        
        {/* Logo: home resets Explore, it does not just switch to the tab. */}
        <button
          type="button"
          onClick={() => (onHome ? onHome() : handleTab('explore'))}
          aria-label="Mitsu home"
          className="flex items-center gap-3 justify-self-start cursor-pointer group bg-transparent border-0 p-0 text-left"
        >
          <div className="w-8 h-8 rounded-lg bg-[var(--surface-color)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-vermillion)] font-bold text-sm shadow-sm group-hover:border-[var(--accent-vermillion)] transition-colors">
            ❖
          </div>
          <div className="hidden flex-col sm:flex">
            <span className="font-heading text-lg md:text-xl font-bold tracking-tight text-[var(--text-color)] leading-tight">
              Mit<span className="text-[var(--accent-vermillion)]">su</span>
            </span>
            <span className="text-[9px] text-[var(--text-muted)] tracking-widest uppercase font-mono">
              AI Manga Discovery
            </span>
          </div>
        </button>

        {/* Navigation Tabs (Centered) — the same CapsuleToggle as the Trending
            rail, at header size: one toggle in the app, two sizes. */}
        <nav aria-label="Primary" className="min-w-0 max-w-full justify-self-center overflow-x-auto no-scrollbar">
          <CapsuleToggle
            label="Primary"
            size="md"
            value={activeTab}
            onChange={handleTab}
            // Tabs are navigation, so the active one is `aria-current="page"`,
            // not a pressed state.
            active="current"
            options={[
              {
                id: 'explore',
                label: 'Explore',
                icon: (
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                )
              },
              {
                id: 'surprise',
                label: 'Surprise Me',
                icon: (
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
                  </svg>
                )
              },
              {
                id: 'bookmarks',
                label: 'Saved',
                badge: bookmarkCount > 0 ? bookmarkCount : null,
                icon: (
                  <svg className="w-3.5 h-3.5" fill={activeTab === 'bookmarks' ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                  </svg>
                )
              }
            ]}
          />
        </nav>

        {/* Settings Button */}
        <button
          onClick={onOpenSettings}
          className="shrink-0 justify-self-end p-2 text-[var(--text-muted)] bg-[var(--surface-color)] border border-[var(--border-color)] rounded-full icon-button-accent cursor-pointer"
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
