import React, { useEffect, useRef } from 'react';

/**
 * Monochrome Cinematic Universe
 * 
 * An advanced high-performance multi-layered animated atmospheric canvas:
 * 1. Subtle Grid Pulse: Technical drafting grid with communicating vertex nodes that flare in and out.
 * 2. Drifting Data Particles: Tiny geometric squares, dots, and binary digits drifting upward.
 * 3. Scanning Line: Wide horizontal radar/CRT scanline with smooth gradient falloff sweeping downward.
 * 4. Minimalist Code Rain: Barely-visible cascading data streams (hex/binary/unicode) at varying speeds.
 * 5. Deep Space Dust & Twinkling Sparkles: Soft nebula dust clouds and faint micro-sparkles.
 * 6. Breathing Ambient Glows: Soft localized glows expanding and contracting behind dashboard modules.
 * 7. Pointer-Reactive Lighting: Smooth radial illumination tracking user interaction.
 */
export default function MonochromeCinematicUniverse() {
  const canvasRef = useRef(null);
  const mousePos = useRef({ x: -1000, y: -1000, targetX: -1000, targetY: -1000 });
  const animFrameId = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const isMobile = width < 768;
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const handleResize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
      initElements();
    };
    window.addEventListener('resize', handleResize);

    const handleMouseMove = (e) => {
      mousePos.current.targetX = e.clientX;
      mousePos.current.targetY = e.clientY;
    };
    window.addEventListener('mousemove', handleMouseMove, { passive: true });

    // =========================================================================
    // 1. Grid & Communicating Pulsing Nodes
    // =========================================================================
    const gridSize = 60;
    let gridNodes = [];

    // =========================================================================
    // 2. Drifting Data Particles (Binary, dots, micro-squares)
    // =========================================================================
    let dataParticles = [];

    // =========================================================================
    // 3. Minimalist Code Rain Columns (Sparse, ultra-low opacity)
    // =========================================================================
    const RAIN_CHARS = '01010148AFE97B_◈◇⟡#$*+';
    let rainColumns = [];

    // =========================================================================
    // 4. Nebula Dust Clusters & Twinkling Sparkles
    // =========================================================================
    let nebulaClusters = [];
    let sparkles = [];

    // =========================================================================
    // 5. Constellation & Floating Financial Glyphs
    // =========================================================================
    const GLYPHS = ['₹', '◈', '◇', '⟡', '∞', '+', '×', '▲', '▼'];
    let floatingGlyphs = [];

    // Initialize all particle sets on mount / resize
    const initElements = () => {
      // 1. Grid Nodes
      gridNodes = [];
      const crossStep = gridSize * 2;
      for (let x = crossStep; x < width; x += crossStep) {
        for (let y = crossStep; y < height; y += crossStep) {
          if (Math.random() < 0.28) {
            gridNodes.push({
              x,
              y,
              pulseSpeed: 0.012 + Math.random() * 0.02,
              pulsePhase: Math.random() * Math.PI * 2,
              maxRadius: 3 + Math.random() * 4,
            });
          }
        }
      }

      // 2. Drifting Data Particles
      dataParticles = [];
      const particleCount = isMobile ? 30 : 75;
      for (let i = 0; i < particleCount; i++) {
        const typeRand = Math.random();
        dataParticles.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.25,
          vy: -0.25 - Math.random() * 0.55, // Drifting upwards
          type: typeRand < 0.4 ? 'binary' : typeRand < 0.7 ? 'square' : 'dot',
          char: Math.random() > 0.5 ? '1' : '0',
          size: 1.2 + Math.random() * 2,
          alpha: 0.08 + Math.random() * 0.16,
        });
      }

      // 3. Code Rain Columns
      rainColumns = [];
      const colSpacing = isMobile ? 65 : 48;
      const totalCols = Math.floor(width / colSpacing);
      for (let i = 0; i < totalCols; i++) {
        if (Math.random() < 0.55) {
          const colLength = 7 + Math.floor(Math.random() * 14);
          const chars = [];
          for (let j = 0; j < colLength; j++) {
            chars.push(RAIN_CHARS[Math.floor(Math.random() * RAIN_CHARS.length)]);
          }
          rainColumns.push({
            x: i * colSpacing + (Math.random() * 15),
            y: Math.random() * height * 1.5 - height * 0.5,
            speed: 0.75 + Math.random() * 1.2,
            chars,
            opacity: 0.035 + Math.random() * 0.045,
            fontSize: 10 + Math.random() * 2,
          });
        }
      }

      // 4. Nebula Clusters & Twinkling Sparkles
      nebulaClusters = [
        { x: width * 0.2, y: height * 0.3, radius: 280, vx: 0.08, vy: 0.05, phase: 0 },
        { x: width * 0.8, y: height * 0.25, radius: 340, vx: -0.06, vy: 0.07, phase: 2 },
        { x: width * 0.5, y: height * 0.75, radius: 380, vx: 0.05, vy: -0.06, phase: 4 },
      ];

      sparkles = [];
      const sparkleCount = isMobile ? 18 : 45;
      for (let i = 0; i < sparkleCount; i++) {
        sparkles.push({
          x: Math.random() * width,
          y: Math.random() * height,
          size: 0.7 + Math.random() * 1.5,
          twinkleSpeed: 0.015 + Math.random() * 0.03,
          twinklePhase: Math.random() * Math.PI * 2,
        });
      }

      // 5. Floating Financial Glyphs
      floatingGlyphs = [];
      const glyphCount = isMobile ? 10 : 22;
      for (let i = 0; i < glyphCount; i++) {
        floatingGlyphs.push({
          char: GLYPHS[Math.floor(Math.random() * GLYPHS.length)],
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.3,
          vy: (Math.random() - 0.5) * 0.3,
          rotation: Math.random() * Math.PI * 2,
          rotSpeed: (Math.random() - 0.5) * 0.006,
          fontSize: 12 + Math.random() * 14,
          alpha: 0.07 + Math.random() * 0.12,
          pulseOffset: Math.random() * Math.PI * 2,
        });
      }
    };

    initElements();

    // Scanline & Tick State
    let scanLineY = 0;
    let tick = 0;

    // =========================================================================
    // Main Render Loop
    // =========================================================================
    const render = () => {
      tick++;

      // Pause rendering if tab hidden
      if (document.hidden) {
        animFrameId.current = requestAnimationFrame(render);
        return;
      }

      // Smooth mouse interpolation
      mousePos.current.x += (mousePos.current.targetX - mousePos.current.x) * 0.08;
      mousePos.current.y += (mousePos.current.targetY - mousePos.current.y) * 0.08;

      ctx.clearRect(0, 0, width, height);

      // =======================================================================
      // Layer 1: Nebula & Deep Space Dust Clouds
      // =======================================================================
      ctx.save();
      nebulaClusters.forEach((neb) => {
        if (!prefersReducedMotion) {
          neb.x += neb.vx;
          neb.y += neb.vy;
          if (neb.x < -100) neb.vx *= -1;
          if (neb.x > width + 100) neb.vx *= -1;
          if (neb.y < -100) neb.vy *= -1;
          if (neb.y > height + 100) neb.vy *= -1;
        }

        const breath = 1 + 0.08 * Math.sin(tick * 0.01 + neb.phase);
        const r = neb.radius * breath;
        const grad = ctx.createRadialGradient(neb.x, neb.y, 0, neb.x, neb.y, r);
        grad.addColorStop(0, 'rgba(255, 255, 255, 0.025)');
        grad.addColorStop(0.5, 'rgba(170, 170, 170, 0.012)');
        grad.addColorStop(1, 'rgba(0, 0, 0, 0)');

        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(neb.x, neb.y, r, 0, Math.PI * 2);
        ctx.fill();
      });

      // Twinkling faint deep space sparkles
      sparkles.forEach((sp) => {
        const spAlpha = 0.04 + 0.18 * Math.pow(Math.sin(tick * sp.twinkleSpeed + sp.twinklePhase), 2);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, sp.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${spAlpha})`;
        ctx.fill();
      });
      ctx.restore();

      // =======================================================================
      // Layer 2: Subtle Drafting Grid with Communicating Node Pulses
      // =======================================================================
      ctx.save();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
      ctx.lineWidth = 0.5;

      // Vertical lines
      for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }

      // Horizontal lines
      for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Static crosshairs (+)
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.09)';
      ctx.lineWidth = 1;
      const crossStep = gridSize * 2;
      for (let x = crossStep; x < width; x += crossStep) {
        for (let y = crossStep; y < height; y += crossStep) {
          ctx.beginPath();
          ctx.moveTo(x - 3, y);
          ctx.lineTo(x + 3, y);
          ctx.moveTo(x, y - 3);
          ctx.lineTo(x, y + 3);
          ctx.stroke();
        }
      }

      // Communicating Pulsing Grid Nodes
      gridNodes.forEach((node) => {
        const pulse = Math.sin(tick * node.pulseSpeed + node.pulsePhase);
        if (pulse > 0.15) {
          const alpha = (pulse - 0.15) / 0.85;
          const currentRadius = 1.5 + node.maxRadius * alpha;

          // Soft halo
          const halo = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, currentRadius * 2.5);
          halo.addColorStop(0, `rgba(255, 255, 255, ${alpha * 0.35})`);
          halo.addColorStop(0.5, `rgba(255, 255, 255, ${alpha * 0.12})`);
          halo.addColorStop(1, 'rgba(255, 255, 255, 0)');

          ctx.fillStyle = halo;
          ctx.beginPath();
          ctx.arc(node.x, node.y, currentRadius * 2.5, 0, Math.PI * 2);
          ctx.fill();

          // Core node point
          ctx.fillStyle = `rgba(255, 255, 255, ${alpha * 0.8})`;
          ctx.beginPath();
          ctx.arc(node.x, node.y, 1.2, 0, Math.PI * 2);
          ctx.fill();
        }
      });
      ctx.restore();

      // =======================================================================
      // Layer 3: Minimalist Matrix-Style Code Rain (Ultra-Subtle)
      // =======================================================================
      ctx.save();
      ctx.font = '500 10px "JetBrains Mono", monospace';
      ctx.textAlign = 'center';

      rainColumns.forEach((col) => {
        if (!prefersReducedMotion) {
          col.y += col.speed;
          if (col.y > height + 250) {
            col.y = -180;
            // Slightly mutate a character
            const rndIdx = Math.floor(Math.random() * col.chars.length);
            col.chars[rndIdx] = RAIN_CHARS[Math.floor(Math.random() * RAIN_CHARS.length)];
          }
        }

        const len = col.chars.length;
        for (let j = 0; j < len; j++) {
          const charY = col.y + j * 16;
          if (charY >= -20 && charY <= height + 20) {
            // Head character is slightly brighter, fading toward tail
            const isHead = j === len - 1;
            const charAlpha = isHead 
              ? col.opacity * 2.2 
              : col.opacity * (j / len);

            ctx.fillStyle = isHead 
              ? `rgba(255, 255, 255, ${Math.min(0.18, charAlpha)})` 
              : `rgba(170, 170, 170, ${charAlpha})`;

            ctx.fillText(col.chars[j], col.x, charY);
          }
        }
      });
      ctx.restore();

      // =======================================================================
      // Layer 4: Drifting Data Particles (Binary 0/1, Dots, Tiny Squares)
      // =======================================================================
      ctx.save();
      ctx.font = '600 9px "JetBrains Mono", monospace';
      ctx.textAlign = 'center';

      dataParticles.forEach((dp) => {
        if (!prefersReducedMotion) {
          dp.x += dp.vx;
          dp.y += dp.vy;

          if (dp.y < -20) {
            dp.y = height + 20;
            dp.x = Math.random() * width;
          }
          if (dp.x < 0) dp.x = width;
          if (dp.x > width) dp.x = 0;
        }

        if (dp.type === 'binary') {
          ctx.fillStyle = `rgba(255, 255, 255, ${dp.alpha})`;
          ctx.fillText(dp.char, dp.x, dp.y);
        } else if (dp.type === 'square') {
          ctx.fillStyle = `rgba(255, 255, 255, ${dp.alpha * 0.9})`;
          ctx.fillRect(dp.x - dp.size / 2, dp.y - dp.size / 2, dp.size, dp.size);
        } else {
          ctx.fillStyle = `rgba(255, 255, 255, ${dp.alpha})`;
          ctx.beginPath();
          ctx.arc(dp.x, dp.y, dp.size / 2, 0, Math.PI * 2);
          ctx.fill();
        }
      });
      ctx.restore();

      // =======================================================================
      // Layer 5: Floating Financial Glyphs (₹, ◈, ◇, ⟡, ∞, +)
      // =======================================================================
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      floatingGlyphs.forEach((s) => {
        if (!prefersReducedMotion) {
          s.x += s.vx;
          s.y += s.vy;
          s.rotation += s.rotSpeed;

          if (s.x < -30) s.x = width + 30;
          if (s.x > width + 30) s.x = -30;
          if (s.y < -30) s.y = height + 30;
          if (s.y > height + 30) s.y = -30;
        }

        const currentAlpha = s.alpha * (0.8 + 0.2 * Math.sin(tick * 0.02 + s.pulseOffset));

        ctx.save();
        ctx.translate(s.x, s.y);
        ctx.rotate(s.rotation);
        ctx.fillStyle = `rgba(255, 255, 255, ${currentAlpha})`;
        ctx.font = `${s.fontSize}px "JetBrains Mono", monospace`;
        ctx.fillText(s.char, 0, 0);
        ctx.restore();
      });
      ctx.restore();

      // =======================================================================
      // Layer 6: Wide Gradient Scanning Line (Radar / CRT Sweep)
      // =======================================================================
      if (!prefersReducedMotion) {
        ctx.save();
        scanLineY = (scanLineY + 0.7) % (height + 240);
        const actualScanY = scanLineY - 120;
        const scanHeight = 160;

        const scanGrad = ctx.createLinearGradient(0, actualScanY, 0, actualScanY + scanHeight);
        scanGrad.addColorStop(0, 'rgba(255, 255, 255, 0)');
        scanGrad.addColorStop(0.45, 'rgba(255, 255, 255, 0.022)');
        scanGrad.addColorStop(0.5, 'rgba(255, 255, 255, 0.045)'); // Center beam
        scanGrad.addColorStop(0.55, 'rgba(255, 255, 255, 0.022)');
        scanGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');

        ctx.fillStyle = scanGrad;
        ctx.fillRect(0, actualScanY, width, scanHeight);
        ctx.restore();
      }

      // =======================================================================
      // Layer 7: Component Breathing Glows & Pointer Spotlight
      // =======================================================================
      ctx.save();
      // Three focal breathing nodes behind key dashboard modules
      const focalPoints = [
        { x: width * 0.5, y: height * 0.18, baseR: 300, phase: 0 },
        { x: width * 0.25, y: height * 0.55, baseR: 260, phase: 2 },
        { x: width * 0.75, y: height * 0.65, baseR: 280, phase: 4 },
      ];

      focalPoints.forEach((fp) => {
        const breathingFactor = 0.85 + 0.15 * Math.sin(tick * 0.015 + fp.phase);
        const r = fp.baseR * breathingFactor;
        const glowGrad = ctx.createRadialGradient(fp.x, fp.y, 0, fp.x, fp.y, r);
        glowGrad.addColorStop(0, 'rgba(255, 255, 255, 0.03)');
        glowGrad.addColorStop(0.5, 'rgba(170, 170, 170, 0.012)');
        glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

        ctx.fillStyle = glowGrad;
        ctx.beginPath();
        ctx.arc(fp.x, fp.y, r, 0, Math.PI * 2);
        ctx.fill();
      });

      // Pointer Spotlight
      if (mousePos.current.x > 0 && mousePos.current.y > 0) {
        const lightGrad = ctx.createRadialGradient(
          mousePos.current.x,
          mousePos.current.y,
          0,
          mousePos.current.x,
          mousePos.current.y,
          340
        );
        lightGrad.addColorStop(0, 'rgba(255, 255, 255, 0.05)');
        lightGrad.addColorStop(0.5, 'rgba(170, 170, 170, 0.018)');
        lightGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = lightGrad;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.restore();

      animFrameId.current = requestAnimationFrame(render);
    };

    // Stop the render loop entirely while the tab is hidden; restart on return.
    // The local version kept scheduling frames while hidden, which wastes CPU
    // and battery on every backgrounded tab. The early return inside render()
    // above stays as a safety net.
    const handleVisibilityChange = () => {
      if (document.hidden) {
        if (animFrameId.current) {
          cancelAnimationFrame(animFrameId.current);
          animFrameId.current = null;
        }
      } else if (!animFrameId.current) {
        animFrameId.current = requestAnimationFrame(render);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    animFrameId.current = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (animFrameId.current) cancelAnimationFrame(animFrameId.current);
    };
  }, []);

  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden bg-black" aria-hidden="true">
      {/* 2D Accelerated Canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 block w-full h-full" />

      {/* Subtle Ambient Radial Vignette */}
      <div className="absolute inset-0 bg-radial-[circle_at_center,transparent_40%,rgba(0,0,0,0.85)_100%]" />
      
      {/* Subtle Corner Technical Telemetry */}
      <div className="absolute top-4 left-6 hidden sm:flex items-center space-x-3 text-[9px] font-mono text-zinc-700 tracking-widest select-none uppercase">
        <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
        <span>ATMOSPHERE // DATA_STREAM_ACTIVE</span>
      </div>

      <div className="absolute top-4 right-6 hidden sm:flex items-center space-x-2 text-[9px] font-mono text-zinc-700 tracking-widest select-none uppercase">
        <span>GRID_PULSE: [SYNC]</span>
        <span>•</span>
        <span>MATRIX_DEPTH: LOW_OPACITY</span>
      </div>
    </div>
  );
}
