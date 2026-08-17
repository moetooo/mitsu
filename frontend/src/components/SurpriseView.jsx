import { useState, useEffect, useRef } from 'react';

export default function SurpriseView({ 
  manga, 
  loading, 
  onRefresh, 
  fetchBatch,
  filters,
  bookmarks = [], 
  onToggleBookmark, 
  onSelectManga 
}) {
  // animStage for button: 'idle' | 'red-entering' | 'red-active' | 'red-exiting'
  const [animStage, setAnimStage] = useState('idle');

  // sliderState for card: 'idle' | 'step_1_slide_left' | 'step_2_wait_loading' | 'step_3_prepare_next' | 'step_4_slide_next'
  const [sliderState, setSliderState] = useState('idle');

  const [displayManga, setDisplayManga] = useState(manga);
  const bufferRef = useRef([]);
  const isFetchingRef = useRef(false);

  // Sync initial manga prop to local display when idle
  useEffect(() => {
    if (manga && !displayManga && animStage === 'idle' && sliderState === 'idle') {
      setDisplayManga(manga);
    }
  }, [manga]);

  // Invalidate buffer whenever filters change
  useEffect(() => {
    bufferRef.current = [];
    refillBuffer();
  }, [filters]);

  const preloadImage = (url) => {
    return new Promise((resolve) => {
      if (!url) { resolve(); return; }
      const img = new Image();
      img.onload = () => resolve();
      img.onerror = () => resolve();
      img.src = url;
    });
  };

  const refillBuffer = async () => {
    if (isFetchingRef.current || bufferRef.current.length >= 5) return;
    isFetchingRef.current = true;
    try {
      if (fetchBatch) {
        const batch = await fetchBatch(5);
        if (Array.isArray(batch) && batch.length > 0) {
          batch.forEach(item => {
            if (item.cover_image_url) {
              preloadImage(item.cover_image_url);
            }
          });
          bufferRef.current = [...bufferRef.current, ...batch];
        }
      }
    } catch (err) {
      console.error('Failed to refill frontend roulette buffer:', err);
    } finally {
      isFetchingRef.current = false;
    }
  };

  const activeManga = displayManga || manga;
  const isBookmarked = activeManga ? (bookmarks || []).some(b => b.id === activeManga.id) : false;

  const handleButtonClick = async () => {
    if (loading || animStage !== 'idle' || sliderState !== 'idle') return;

    // 1. Start button red slider & trigger Step 1: Manga 1 slides left, Click state slides in from right to center
    setAnimStage('red-entering');
    setSliderState('step_1_slide_left');

    // 2. Asynchronously fetch next candidate & preload cover image
    const fetchCandidatePromise = (async () => {
      let nextManga = null;
      if (bufferRef.current.length > 0) {
        nextManga = bufferRef.current.shift();
        if (bufferRef.current.length < 3) {
          refillBuffer();
        }
      } else if (onRefresh) {
        nextManga = await onRefresh();
      }
      if (nextManga?.cover_image_url) {
        await preloadImage(nextManga.cover_image_url);
      }
      return nextManga;
    })();

    // Minimum time for Step 1 slide-in animation into center (400ms)
    const step1AnimPromise = new Promise(resolve => setTimeout(resolve, 400));

    // Wait until Step 1 animation finishes sliding into center
    await step1AnimPromise;

    // Set state to 'step_2_wait_loading': Click state sits in center while waiting for fetch + image preload
    setSliderState('step_2_wait_loading');
    setAnimStage('red-active');

    // Wait for data & image preloading to complete fully
    const nextManga = await fetchCandidatePromise;

    // 3. Once loading is complete, update displayManga and prepare Manga 2 off-screen RIGHT
    if (nextManga) {
      setDisplayManga(nextManga);
    }
    setSliderState('step_3_prepare_next');

    // Brief DOM tick to apply position before animation trigger
    await new Promise(resolve => setTimeout(resolve, 20));

    // 4. Trigger Step 4: Click state slides out to LEFT, Manga 2 slides in from RIGHT to CENTER
    setAnimStage('red-exiting');
    setSliderState('step_4_slide_next');

    // Wait for Step 4 slide animation to complete (400ms)
    await new Promise(resolve => setTimeout(resolve, 400));

    // 5. Reset button and card to stable idle state
    setAnimStage('idle');
    setSliderState('idle');
  };

  const getCleanSynopsis = (text) => {
    if (!text) return 'No synopsis description available for this title.';
    return text.replace(/<[^>]*>?/gm, '');
  };

  // Button red slider positioning
  const getRedSliderClass = () => {
    switch (animStage) {
      case 'red-entering':
        return 'translate-x-0 transition-transform duration-400 ease-in-out';
      case 'red-active':
        return 'translate-x-0';
      case 'red-exiting':
        return '-translate-x-full transition-transform duration-400 ease-in-out';
      case 'idle':
      default:
        return 'translate-x-full';
    }
  };

  // Button default text entrance
  const getDefaultContentClass = () => {
    switch (animStage) {
      case 'red-entering':
      case 'red-active':
        return 'opacity-0 translate-x-6 pointer-events-none transition-all duration-400 ease-in-out';
      case 'red-exiting':
        return 'opacity-100 translate-x-0 transition-all duration-400 ease-in-out';
      case 'idle':
      default:
        return 'opacity-100 translate-x-0';
    }
  };

  // Click State Screen (Zen Pebble loading pass) positioning
  const getClickStateScreenClass = () => {
    switch (sliderState) {
      case 'step_1_slide_left':
      case 'step_2_wait_loading':
      case 'step_3_prepare_next':
        return 'translate-x-0 opacity-100 transition-all duration-400 ease-in-out z-30';
      case 'step_4_slide_next':
        return '-translate-x-full opacity-0 transition-all duration-400 ease-in-out pointer-events-none z-30';
      case 'idle':
      default:
        return 'translate-x-full opacity-0 pointer-events-none z-10';
    }
  };

  // Current Manga Pass positioning
  const getCurrentMangaCardClass = () => {
    switch (sliderState) {
      case 'step_1_slide_left':
      case 'step_2_wait_loading':
        return '-translate-x-full opacity-0 transition-all duration-400 ease-in-out pointer-events-none z-10';
      case 'step_3_prepare_next':
        return 'translate-x-full opacity-0 pointer-events-none z-20';
      case 'step_4_slide_next':
        return 'translate-x-0 opacity-100 transition-all duration-400 ease-in-out z-20';
      case 'idle':
      default:
        return 'translate-x-0 opacity-100 z-20';
    }
  };

  return (
    <div className="pt-4 pb-24 max-w-4xl mx-auto space-y-6 animate-in fade-in duration-300">

      {/* TRIGGER BUTTON: CLEAN & MINIMAL BIDIRECTIONAL RED SLIDING BUTTON */}
      <div className="flex justify-center w-full">
        <button
          type="button"
          onClick={handleButtonClick}
          disabled={loading || animStage !== 'idle' || sliderState !== 'idle'}
          className="group relative inline-flex items-center h-11 px-7 rounded-full bg-[var(--surface-color)] border border-[var(--border-color)] hover:border-[var(--accent-vermillion)] text-[var(--text-color)] shadow-sm transition-all duration-300 cursor-pointer disabled:opacity-80 shrink-0 overflow-hidden"
        >
          {/* Default Text: Slides in from RIGHT to center when returning */}
          <div className={`flex items-center transition-all ${getDefaultContentClass()}`}>
            <span className="text-xs font-mono font-bold tracking-widest uppercase text-[var(--text-color)]">
              DISCOVER TITLE
            </span>
          </div>

          {/* Red Sliding Panel */}
          <div 
            className={`absolute inset-0 bg-[var(--accent-vermillion)] text-white flex items-center justify-center px-7 font-mono text-xs font-bold tracking-widest uppercase z-10 ${getRedSliderClass()}`}
          >
            <span>DISCOVERING...</span>
          </div>
        </button>
      </div>

      {/* RECTANGULAR BOARDING PASS SLIDER STAGE */}
      {loading && !activeManga ? (
        <div className="w-full max-w-[660px] mx-auto h-[260px] flex flex-col items-center justify-center space-y-3 bg-[var(--surface-color)]/30 border border-[var(--border-color)] rounded-2xl backdrop-blur-md">
          <div className="w-8 h-8 border-2 border-[var(--accent-vermillion)] border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-mono text-[var(--text-muted)] tracking-widest uppercase animate-pulse">
            Consulting Candidate Engine...
          </span>
        </div>
      ) : activeManga ? (
        <div className="max-w-[660px] mx-auto min-h-[260px] relative overflow-hidden">
          
          {/* 1. CLICK STATE SCREEN (Zen Pebble pass with Mitsu Mon Glyph ❖ loading indicator) */}
          <div 
            className={`absolute inset-0 flex items-center justify-center rounded-2xl shadow-md bg-[var(--surface-color)]/95 backdrop-blur-xl border border-[var(--border-color)] text-[var(--text-color)] ${getClickStateScreenClass()}`}
          >
            <div className="flex items-center justify-center">
              <span className="text-2xl text-[var(--accent-vermillion)] animate-pulse select-none font-bold">
                ❖
              </span>
            </div>
          </div>

          {/* 2. MANGA BOARDING PASS (Slides left on click, then next slides in from right to center) */}
          <div className={`w-full min-h-[260px] flex flex-col justify-center bg-[var(--surface-color)]/90 backdrop-blur-xl border border-[var(--border-color)] rounded-2xl p-4 sm:p-5 shadow-md ${getCurrentMangaCardClass()}`}>
            
            <div className="flex flex-col sm:flex-row gap-5 items-center">
              
              {/* LEFT STUB: POSTER COVER */}
              <div className="w-32 h-44 shrink-0 border-r-0 sm:border-r border-dashed border-[var(--border-color)] pr-0 sm:pr-5 flex items-center justify-center">
                <div className="w-32 h-44 rounded-lg overflow-hidden border border-[var(--border-color)] bg-[var(--bg-color)] shadow-xs relative shrink-0">
                  {activeManga.cover_image_url && (
                    <img 
                      src={activeManga.cover_image_url} 
                      alt={activeManga.title} 
                      className="w-full h-full object-cover"
                    />
                  )}
                </div>
              </div>

              {/* RIGHT PANEL: STARLIGHT SYNOPSIS */}
              <div className="flex-1 space-y-2.5 min-w-0">
                
                {/* Title */}
                <div>
                  <h3 className="font-serif-jp text-xl font-bold text-[var(--text-color)] truncate">
                    {activeManga.title}
                  </h3>
                </div>

                {/* Genre Chips */}
                <div className="flex flex-wrap gap-1.5">
                  {(activeManga.genres || ['Fantasy', 'Adventure']).slice(0, 3).map((genre) => (
                    <span
                      key={genre}
                      className="rounded-full bg-[var(--bg-color)] border border-[var(--border-color)] px-2.5 py-0.5 text-[10px] font-mono text-[var(--text-color)]"
                    >
                      #{genre}
                    </span>
                  ))}
                </div>

                {/* Synopsis Quote */}
                <div>
                  <p className="text-xs font-serif-jp text-[var(--text-muted)] italic leading-relaxed line-clamp-2 h-9 overflow-hidden">
                    "{getCleanSynopsis(activeManga.synopsis)}"
                  </p>
                  <div className="h-[1px] bg-gradient-to-r from-[var(--accent-vermillion)]/40 via-[var(--border-color)] to-transparent w-full mt-2" />
                </div>

                {/* Action Footer */}
                <div className="flex items-center gap-2.5 pt-0.5">
                  <button
                    type="button"
                    onClick={() => onToggleBookmark(activeManga)}
                    className="rounded-full border border-[var(--border-color)] bg-[var(--bg-color)] px-3.5 py-1.5 text-xs font-mono text-[var(--text-color)] hover:border-[var(--text-muted)] transition-colors cursor-pointer"
                  >
                    {isBookmarked ? 'Saved' : 'Save Title'}
                  </button>

                  {onSelectManga && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectManga(activeManga);
                      }}
                      className="bg-[var(--accent-vermillion)] text-white rounded-full px-4 py-1.5 text-xs font-mono font-bold hover:opacity-90 active:scale-95 transition-all shadow-xs cursor-pointer"
                    >
                      Full Details →
                    </button>
                  )}
                </div>

              </div>

            </div>
          </div>
        </div>
      ) : null}

    </div>
  );
}
