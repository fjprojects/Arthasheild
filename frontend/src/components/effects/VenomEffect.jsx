import React, { useEffect, useRef } from 'react';

/**
 * Venom Ink Interaction Effect
 * Spawns organic monochrome liquid-ink tendrils, silver particles,
 * and an expanding energy ripple from the exact point of interaction.
 * Applied globally to all buttons and interactive controls across ArthaShield.
 */
export default function VenomEffect() {
  const canvasRef = useRef(null);
  const burstsRef = useRef([]);
  const animFrameRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const handleResize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    handleResize();
    window.addEventListener('resize', handleResize);

    // Particle / Tendril Burst Generator
    const createBurst = (x, y, buttonEl) => {
      // 1. Button compression & border flash
      if (buttonEl) {
        buttonEl.classList.remove('venom-flash-active');
        // Force reflow
        void buttonEl.offsetWidth;
        buttonEl.classList.add('venom-flash-active');
        setTimeout(() => {
          buttonEl.classList.remove('venom-flash-active');
        }, 400);
      }

      // 2. Generate branching tendrils (8-14 tendrils)
      const tendrilCount = 10 + Math.floor(Math.random() * 5);
      const tendrils = [];
      for (let i = 0; i < tendrilCount; i++) {
        const baseAngle = (i / tendrilCount) * Math.PI * 2 + (Math.random() - 0.5) * 0.4;
        const maxDist = 28 + Math.random() * 32;
        const curveOffset = (Math.random() - 0.5) * 20;
        tendrils.push({
          angle: baseAngle,
          maxDist,
          curveOffset,
          width: 1.5 + Math.random() * 1.8,
          color: Math.random() > 0.4 ? '#FFFFFF' : '#AAAAAA',
          progress: 0,
          speed: 0.08 + Math.random() * 0.06,
        });
      }

      // 3. Generate scattering micro-particles (18-26 particles)
      const particleCount = 20 + Math.floor(Math.random() * 8);
      const particles = [];
      for (let i = 0; i < particleCount; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 1.8 + Math.random() * 4.2;
        particles.push({
          x,
          y,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          size: 0.8 + Math.random() * 2.2,
          color: Math.random() > 0.3 ? '#FFFFFF' : (Math.random() > 0.5 ? '#AAAAAA' : '#E0E0E0'),
          alpha: 1.0,
          decay: 0.035 + Math.random() * 0.035,
          friction: 0.94,
        });
      }

      burstsRef.current.push({
        x,
        y,
        age: 0,
        maxAge: 32, // frames (~500ms)
        tendrils,
        particles,
        rippleRadius: 2,
        maxRippleRadius: 42 + Math.random() * 16,
      });

      if (!animFrameRef.current) {
        animFrameRef.current = requestAnimationFrame(render);
      }
    };

    // Animation Render Loop
    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (let bIndex = burstsRef.current.length - 1; bIndex >= 0; bIndex--) {
        const burst = burstsRef.current[bIndex];
        burst.age++;

        const lifeRatio = burst.age / burst.maxAge; // 0 to 1
        const fade = Math.max(0, 1 - lifeRatio);

        // A. Draw Circular Energy Ripple
        burst.rippleRadius += (burst.maxRippleRadius - burst.rippleRadius) * 0.18;
        ctx.save();
        ctx.beginPath();
        ctx.arc(burst.x, burst.y, burst.rippleRadius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255, 255, 255, ${fade * 0.75})`;
        ctx.lineWidth = Math.max(0.6, 2.2 * (1 - lifeRatio));
        ctx.stroke();

        // Inner shockwave line
        ctx.beginPath();
        ctx.arc(burst.x, burst.y, burst.rippleRadius * 0.65, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(170, 170, 170, ${fade * 0.45})`;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();

        // B. Draw Liquid-Ink Tendrils
        burst.tendrils.forEach((t) => {
          t.progress = Math.min(1, t.progress + t.speed);
          const currentDist = t.maxDist * Math.sin(t.progress * Math.PI * 0.5);
          const endX = burst.x + Math.cos(t.angle) * currentDist;
          const endY = burst.y + Math.sin(t.angle) * currentDist;

          // Perpendicular curve vector
          const midDist = currentDist * 0.5;
          const normalAngle = t.angle + Math.PI / 2;
          const ctrlX = burst.x + Math.cos(t.angle) * midDist + Math.cos(normalAngle) * t.curveOffset;
          const ctrlY = burst.y + Math.sin(t.angle) * midDist + Math.sin(normalAngle) * t.curveOffset;

          ctx.save();
          ctx.beginPath();
          ctx.moveTo(burst.x, burst.y);
          ctx.quadraticCurveTo(ctrlX, ctrlY, endX, endY);
          ctx.strokeStyle = t.color;
          ctx.globalAlpha = fade * (1 - t.progress * 0.2);
          ctx.lineWidth = t.width * (1 - t.progress * 0.5);
          ctx.lineCap = 'round';
          ctx.stroke();

          // Liquid ink droplet at tip
          if (t.progress < 0.9) {
            ctx.beginPath();
            ctx.arc(endX, endY, (t.width * 1.1) * fade, 0, Math.PI * 2);
            ctx.fillStyle = '#FFFFFF';
            ctx.fill();
          }
          ctx.restore();
        });

        // C. Draw Scattering Micro-Particles
        burst.particles.forEach((p) => {
          p.x += p.vx;
          p.y += p.vy;
          p.vx *= p.friction;
          p.vy *= p.friction;
          p.alpha -= p.decay;

          if (p.alpha > 0) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(p.x, p.y, Math.max(0.4, p.size * p.alpha), 0, Math.PI * 2);
            ctx.fillStyle = p.color;
            ctx.globalAlpha = Math.max(0, p.alpha * fade);
            ctx.shadowColor = '#FFFFFF';
            ctx.shadowBlur = 4;
            ctx.fill();
            ctx.restore();
          }
        });

        // Remove expired bursts
        if (burst.age >= burst.maxAge) {
          burstsRef.current.splice(bIndex, 1);
        }
      }

      if (burstsRef.current.length > 0) {
        animFrameRef.current = requestAnimationFrame(render);
      } else {
        animFrameRef.current = null;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    };

    // Global Click / Pointer Listener for ALL buttons
    const handleGlobalPointerDown = (e) => {
      // Find closest interactive button or clickable element
      const target = e.target;
      const button = target.closest('button, [role="button"], input[type="submit"], .clickable-interactive');
      if (!button) return;

      const rect = button.getBoundingClientRect();
      const x = e.clientX || (rect.left + rect.width / 2);
      const y = e.clientY || (rect.top + rect.height / 2);

      createBurst(x, y, button);
    };

    // Keyboard Accessibility (Enter / Space on buttons)
    const handleGlobalKeyDown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        const active = document.activeElement;
        if (active && (active.tagName === 'BUTTON' || active.getAttribute('role') === 'button')) {
          const rect = active.getBoundingClientRect();
          createBurst(rect.left + rect.width / 2, rect.top + rect.height / 2, active);
        }
      }
    };

    window.addEventListener('pointerdown', handleGlobalPointerDown, { passive: true });
    window.addEventListener('keydown', handleGlobalKeyDown, { passive: true });

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('pointerdown', handleGlobalPointerDown);
      window.removeEventListener('keydown', handleGlobalKeyDown);
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-[9999]"
      aria-hidden="true"
    />
  );
}

