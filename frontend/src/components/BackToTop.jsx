import { useState, useEffect } from 'react';

export default function BackToTop() {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const toggleVisibility = () => {
      if (window.scrollY > 400) {
        setIsVisible(true);
      } else {
        setIsVisible(false);
      }
    };

    window.addEventListener('scroll', toggleVisibility, { passive: true });
    return () => window.removeEventListener('scroll', toggleVisibility);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: 'smooth'
    });
  };

  if (!isVisible) return null;

  return (
    <button
      type="button"
      onClick={scrollToTop}
      className="fixed bottom-6 right-6 z-40 w-11 h-11 rounded-2xl bg-[var(--surface-color)]/90 backdrop-blur-md border border-[var(--border-color)] text-[var(--accent-vermillion)] hover:text-white hover:bg-[var(--accent-vermillion)] hover:border-[var(--accent-vermillion)] transition-all duration-200 shadow-xl flex items-center justify-center cursor-pointer group active:scale-95 animate-in fade-in zoom-in-95"
      title="Scroll to Top"
    >
      {/* Upward Chevron Arrow Icon */}
      <svg 
        className="w-5.5 h-5.5 transition-transform duration-200 group-hover:-translate-y-0.5" 
        fill="none" 
        viewBox="0 0 24 24" 
        stroke="currentColor"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 15l7-7 7 7" />
      </svg>
    </button>
  );
}
