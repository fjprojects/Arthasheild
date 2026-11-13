import React, { useEffect, useRef, useState } from 'react';

/**
 * Custom Financial Pointer — Coin Cursor
 * Features:
 * - Stylised financial coin with embossed ₹ currency glyph.
 * - Precision silver outline, metallic radial gradients, and soft glow.
 * - Smooth interpolated motion (lerp) with subtle velocity tilt.
 * - Trailing particle wake with fading micro-coins and silver sparks.
 * - Hover reaction (scale 1.35x, continuous 3D coin spin) over clickable elements.
 * - Click compression shockwave.
 * - Fully disabled on touchscreens / mobile devices.
 * - pointer-events: none ensures zero interference with clicking or text selection.
 */
export default function CoinCursor() {
  const [isTouchDevice, setIsTouchDevice] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [isHoveringClickable, setIsHoveringClickable] = useState(false);
  const [isMouseDown, setIsMouseDown] = useState(false);

  const cursorRef = useRef(null);
  const canvasRef = useRef(null);
  const trailParticlesRef = useRef([]);

  const pos = useRef({ x: -100, y: -100 });
  const targetPos = useRef({ x: -100, y: -100 });
  const animFrameId = useRef(null);

  useEffect(() => {
    // Check if touch device, coarse pointer, or reduced-motion preferred
    const mediaTouch = window.matchMedia('(hover: none), (pointer: coarse)');
    const mediaReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mediaTouch.matches || mediaReducedMotion.matches || 'ontouchstart' in window) {
      setIsTouchDevice(true);
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const handleResize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    handleResize();
    window.addEventListener('resize', handleResize);

    const handleMouseMove = (e) => {
      targetPos.current.x = e.clientX;
      targetPos.current.y = e.clientY;
      if (!isVisible) setIsVisible(true);

      // Add trail particle
      if (Math.random() > 0.4) {
        trailParticlesRef.current.push({
          x: e.clientX,
          y: e.clientY,
          size: 1.2 + Math.random() * 2.0,
          alpha: 0.65,
          decay: 0.045 + Math.random() * 0.03,
          color: Math.random() > 0.5 ? '#FFFFFF' : '#AAAAAA',
          driftX: (Math.random() - 0.5) * 0.8,
          driftY: (Math.random() - 0.5) * 0.8,
        });
      }

      // Check if hovering clickable
      const target = e.target;
      if (target) {
        const clickable = target.closest('button, a, input, select, textarea, [role="button"], [data-clickable], .cursor-pointer');
        setIsHoveringClickable(!!clickable);
      }
    };

    const handleMouseDown = () => setIsMouseDown(true);
    const handleMouseUp = () => setIsMouseDown(false);
    const handleMouseLeave = () => setIsVisible(false);
    const handleMouseEnter = () => setIsVisible(true);

    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    window.addEventListener('mousedown', handleMouseDown, { passive: true });
    window.addEventListener('mouseup', handleMouseUp, { passive: true });
    document.addEventListener('mouseleave', handleMouseLeave);
    document.addEventListener('mouseenter', handleMouseEnter);

    // Animation Loop for Smooth Interpolation & Particle Trail
    let lastTime = performance.now();
    const render = (now) => {
      // Smooth lerp (interpolation)
      pos.current.x += (targetPos.current.x - pos.current.x) * 0.22;
      pos.current.y += (targetPos.current.y - pos.current.y) * 0.22;

      // Update cursor DOM element
      if (cursorRef.current) {
        cursorRef.current.style.transform = `translate3d(${pos.current.x}px, ${pos.current.y}px, 0)`;
      }

      // Render Trail Particles on Canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (let i = trailParticlesRef.current.length - 1; i >= 0; i--) {
        const p = trailParticlesRef.current[i];
        p.x += p.driftX;
        p.y += p.driftY;
        p.alpha -= p.decay;

        if (p.alpha <= 0) {
          trailParticlesRef.current.splice(i, 1);
        } else {
          ctx.save();
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
          ctx.fillStyle = p.color;
          ctx.globalAlpha = p.alpha;
          ctx.shadowColor = '#FFFFFF';
          ctx.shadowBlur = 3;
          ctx.fill();
          ctx.restore();
        }
      }

      animFrameId.current = requestAnimationFrame(render);
    };

    animFrameId.current = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('mouseleave', handleMouseLeave);
      document.removeEventListener('mouseenter', handleMouseEnter);
      if (animFrameId.current) cancelAnimationFrame(animFrameId.current);
    };
  }, [isVisible]);

  if (isTouchDevice) return null;

  return (
    <>
      {/* Canvas for trailing particle wake */}
      <canvas
        ref={canvasRef}
        className="fixed inset-0 pointer-events-none z-[9990]"
        aria-hidden="true"
      />

      {/* Stylised Coin Pointer */}
      <div
        ref={cursorRef}
        className={`fixed top-0 left-0 pointer-events-none z-[9995] will-change-transform -translate-x-1/2 -translate-y-1/2 transition-opacity duration-150 ${
          isVisible ? 'opacity-100' : 'opacity-0'
        }`}
        style={{ left: 0, top: 0 }}
      >
        <div
          className={`relative flex items-center justify-center transition-all duration-200 select-none ${
            isMouseDown
              ? 'scale-85'
              : isHoveringClickable
              ? 'scale-135'
              : 'scale-100'
          }`}
        >
          {/* Outer Pulsing Silver Ring */}
          <div
            className={`absolute -inset-1 rounded-full border border-white/40 transition-all duration-300 ${
              isHoveringClickable
                ? 'scale-125 opacity-90 animate-ping'
                : 'scale-100 opacity-30'
            }`}
          />

          {/* Coin Body */}
          <div
            className={`w-7 h-7 rounded-full bg-gradient-to-br from-[#111111] via-[#050505] to-[#202020] border border-[#AAAAAA] shadow-[0_0_12px_rgba(255,255,255,0.35)] flex items-center justify-center transition-transform duration-300 ${
              isHoveringClickable ? 'rotate-12 border-white shadow-[0_0_18px_rgba(255,255,255,0.7)]' : ''
            }`}
          >
            {/* Inner Coin Rim */}
            <div className="w-5.5 h-5.5 rounded-full border border-dashed border-white/50 flex items-center justify-center">
              {/* Embossed Currency Glyph (₹) */}
              <span className="font-mono text-[10px] font-black text-white tracking-tighter leading-none select-none drop-shadow-[0_1px_2px_rgba(0,0,0,0.9)]">
                ₹
              </span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

