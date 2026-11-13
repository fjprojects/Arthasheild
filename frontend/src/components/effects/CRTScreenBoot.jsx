import React, { useState, useEffect } from 'react';

/**
 * CRTScreenBoot Component
 * 
 * Simulates a retro CRT monitor powering on:
 * A bright horizontal line rapidly flashes and expands vertically into the full dashboard,
 * running for ~0.45s before fading away completely.
 */
export default function CRTScreenBoot({ triggerKey = null }) {
  const [active, setActive] = useState(true);

  useEffect(() => {
    setActive(true);
    const timer = setTimeout(() => {
      setActive(false);
    }, 450);

    return () => clearTimeout(timer);
  }, [triggerKey]);

  if (!active) return null;

  return (
    <div 
      className="fixed inset-0 z-50 pointer-events-none overflow-hidden flex items-center justify-center bg-transparent"
      aria-hidden="true"
    >
      <div className="w-full h-full bg-white/10 animate-crt-boot shadow-[0_0_100px_rgba(255,255,255,0.4)]" />
    </div>
  );
}

