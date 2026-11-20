import React, { useState, useEffect } from 'react';
import { ArrowUp } from 'lucide-react';

/**
 * Accessible, floating Back to Top button matching ArthaShield monochrome design.
 * Appears only when the page or main scroll container is scrolled down past the threshold (350px).
 * Renamed to "BACK TO TOP" per specification.
 */
export default function BackToTop({ threshold = 350, scrollContainerId = 'main-scroll-container' }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      const container = document.getElementById(scrollContainerId);
      const containerScroll = container ? container.scrollTop : 0;
      const windowScroll = window.scrollY || document.documentElement.scrollTop || 0;
      setVisible(containerScroll > threshold || windowScroll > threshold);
    };

    const container = document.getElementById(scrollContainerId);
    if (container) {
      container.addEventListener('scroll', handleScroll, { passive: true });
    }
    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll(); // Initial check

    return () => {
      if (container) {
        container.removeEventListener('scroll', handleScroll);
      }
      window.removeEventListener('scroll', handleScroll);
    };
  }, [threshold, scrollContainerId]);

  const scrollToTop = () => {
    const container = document.getElementById(scrollContainerId);
    if (container) {
      container.scrollTo({
        top: 0,
        behavior: 'smooth',
      });
    }
    window.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  };

  if (!visible) return null;

  return (
    <button
      type="button"
      onClick={scrollToTop}
      aria-label="Back to top of page"
      className="fixed bottom-6 right-6 md:bottom-8 md:right-8 z-40 flex items-center gap-1.5 px-3 py-2 bg-black/95 hover:bg-white text-[#AAAAAA] hover:text-black border border-[#333333] hover:border-white font-mono text-[9px] uppercase tracking-widest font-bold shadow-[0_0_20px_rgba(0,0,0,0.8)] backdrop-blur-md transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-black select-none"
    >
      <ArrowUp className="w-3.5 h-3.5 shrink-0" />
      <span>BACK TO TOP</span>
    </button>
  );
}
