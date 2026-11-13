import React, { useEffect, useRef } from 'react';
import {
  createSandSimulation,
  GRAIN_ALPHAS,
  TUNING,
} from './ambientSand';

/**
 * AmbientBackground
 *
 * A persistent, site-wide organic sand-texture background.
 *
 * Visual model
 * ------------
 * 1. DUNES (low-resolution canvas): a domain-warped fractal noise field
 *    sampled into a coarse grid and scaled up by the browser. The warping
 *    folds the contours into large, slowly morphing, swirling organic masses
 *    with deep shadowed voids between them.
 * 2. GRAINS (full-resolution canvas): fine grains carried by a
 *    divergence-free curl flow. They brighten inside the dense bands of the
 *    same noise field, so the grain always lies inside the shapes it appears
 *    to form. A slow alpha fade dissolves the old trails, so the texture
 *    rebuilds itself continuously rather than looping.
 *
 * The motion model lives in `ambientSand.js` so it can be verified and
 * measured without a browser.
 *
 * Engineering notes
 * -----------------
 * - One requestAnimationFrame loop drives both canvases. The component holds
 *   no React state, so the animation never triggers a re-render.
 * - Capped at 30 FPS: the effect is slow and organic, so the extra frames are
 *   invisible but would double the cost.
 * - The simulation clock only advances while the loop runs, so a backgrounded
 *   tab resumes exactly where it paused - there is no jump and no restart.
 * - `prefers-reduced-motion` renders a single static frame.
 * - The loop stops entirely while the document is hidden.
 */

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const MAX_FPS = 30;
const FRAME_MS = 1000 / MAX_FPS;
/** Frames of simulation used to build the static reduced-motion frame. */
const STATIC_FRAMES = 120;

export default function AmbientBackground() {
  const canvasRef = useRef(null);
  const duneRef = useRef(null);
  // Loop state lives in refs: it is mutated by the animation loop and by the
  // cleanup, and it must never trigger a render.
  const disposedRef = useRef(false);
  const runningRef = useRef(false);
  const resizeTimerRef = useRef(null);
  const rafIdRef = useRef(null);
  const lastTimestampRef = useRef(0);
  const sizeRef = useRef({ width: 0, height: 0 });

  useEffect(() => {
    // React may run this effect more than once for the same component
    // instance - StrictMode does it deliberately in development, and a hot
    // reload does it too. The state of the previous run must never block the
    // new one, so the loop flags and the viewport size are reset here.
    disposedRef.current = false;
    runningRef.current = false;
    rafIdRef.current = null;
    lastTimestampRef.current = 0;
    sizeRef.current = { width: 0, height: 0 };

    const canvas = canvasRef.current;
    const duneCanvas = duneRef.current;
    if (!canvas || !duneCanvas) return undefined;

    const ctx = canvas.getContext('2d');
    const duneCtx = duneCanvas.getContext('2d');
    if (!ctx || !duneCtx) return undefined;

    const motionQuery = window.matchMedia(REDUCED_MOTION_QUERY);

    
    
    

    const simulation = createSandSimulation({
      width: window.innerWidth,
      height: window.innerHeight,
    });

    // Grains are grouped into brightness buckets so the whole field is drawn
    // with a handful of fillStyle changes instead of one per grain.
    const bucketLists = GRAIN_ALPHAS.map(() => []);

    const resize = () => {
      const nextWidth = window.innerWidth;
      const nextHeight = window.innerHeight;
      const size = sizeRef.current;
      if (nextWidth === size.width && nextHeight === size.height) return;

      sizeRef.current = { width: nextWidth, height: nextHeight };
      canvas.width = nextWidth;
      canvas.height = nextHeight;

      simulation.resize(nextWidth, nextHeight);

      const dune = simulation.dune;
      duneCanvas.width = dune.cols;
      duneCanvas.height = dune.rows;
      // Populate the field immediately so the texture is present on the very
      // first paint rather than only once the animation starts.
      dune.fill(0);
    };

    /** Draws the grains produced by the current simulation step. */
    const paintGrains = () => {
      const commands = simulation.commands;
      const count = simulation.commandCount;

      for (let b = 0; b < bucketLists.length; b++) bucketLists[b].length = 0;
      for (let i = 0; i < count; i++) {
        const offset = i * 4;
        bucketLists[commands[offset + 3]].push(
          commands[offset],
          commands[offset + 1],
          commands[offset + 2],
        );
      }

      for (let b = 0; b < bucketLists.length; b++) {
        const list = bucketLists[b];
        if (!list.length) continue;
        ctx.fillStyle = 'rgba(255, 255, 255, ' + GRAIN_ALPHAS[b] + ')';
        for (let i = 0; i < list.length; i += 3) {
          ctx.fillRect(list[i], list[i + 1], list[i + 2], list[i + 2]);
        }
      }
    };

    /**
     * Fades the previous trails so the texture keeps rebuilding itself.
     *
     * The grain layer is transparent, so the fade has to erase alpha rather
     * than paint black - otherwise the canvas would slowly turn into an
     * opaque black sheet and hide the layers beneath it.
     */
    const fadeTrails = () => {
      const size = sizeRef.current;
      ctx.globalCompositeOperation = 'destination-out';
      ctx.fillStyle = 'rgba(0, 0, 0, ' + TUNING.TRAIL_FADE + ')';
      ctx.fillRect(0, 0, size.width, size.height);
      ctx.globalCompositeOperation = 'source-over';
    };

    /** Uploads the coarse dune field; the browser scales it up smoothly. */
    const paintDunes = () => {
      const dune = simulation.dune;
      const image = duneCtx.createImageData(dune.cols, dune.rows);
      image.data.set(dune.data);
      duneCtx.putImageData(image, 0, 0);
    };

    /** Builds a single, fully developed still frame (reduced motion). */
    const paintStaticFrame = () => {
      const size = sizeRef.current;
      ctx.clearRect(0, 0, size.width, size.height);
      simulation.dune.fill(18);
      // Many short steps build the same density a live frame has.
      for (let i = 0; i < STATIC_FRAMES; i++) {
        simulation.step(1 / 60);
        paintGrains();
      }
      paintDunes();
    };

    const render = (timestamp) => {
      if (disposedRef.current) return;
      rafIdRef.current = requestAnimationFrame(render);

      if (!lastTimestampRef.current) lastTimestampRef.current = timestamp;
      const elapsed = timestamp - lastTimestampRef.current;
      if (elapsed < FRAME_MS) return;
      lastTimestampRef.current = timestamp;

      fadeTrails();
      simulation.step(elapsed / 1000);
      paintGrains();
      paintDunes();
    };

    const start = () => {
      if (runningRef.current || disposedRef.current) return;
      runningRef.current = true;
      lastTimestampRef.current = 0;
      rafIdRef.current = requestAnimationFrame(render);
    };

    const stop = () => {
      if (!runningRef.current) return;
      runningRef.current = false;
      if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    };

    const applyMotionPreference = () => {
      if (motionQuery.matches) {
        stop();
        paintStaticFrame();
      } else {
        start();
      }
    };

    // --- lifecycle ---------------------------------------------------------
    resize();
    paintDunes();
    applyMotionPreference();

    
    const handleResize = () => {
      if (resizeTimerRef.current) clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = setTimeout(() => {
        resize();
        if (motionQuery.matches) paintStaticFrame();
        else paintDunes();
      }, 180);
    };
    window.addEventListener('resize', handleResize, { passive: true });

    // Stop drawing entirely while the tab is in the background.
    const handleVisibility = () => {
      if (document.hidden) {
        stop();
      } else if (!motionQuery.matches) {
        start();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    const handleMotionChange = () => applyMotionPreference();
    if (typeof motionQuery.addEventListener === 'function') {
      motionQuery.addEventListener('change', handleMotionChange);
    } else if (typeof motionQuery.addListener === 'function') {
      motionQuery.addListener(handleMotionChange);
    }

    return () => {
      disposedRef.current = true;
      stop();
      if (resizeTimerRef.current) clearTimeout(resizeTimerRef.current);
      window.removeEventListener('resize', handleResize);
      document.removeEventListener('visibilitychange', handleVisibility);
      if (typeof motionQuery.removeEventListener === 'function') {
        motionQuery.removeEventListener('change', handleMotionChange);
      } else if (typeof motionQuery.removeListener === 'function') {
        motionQuery.removeListener(handleMotionChange);
      }
    };
  }, []);

  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden" aria-hidden="true">
      {/* Large, soft, morphing organic masses (coarse field, scaled up) */}
      <canvas ref={duneRef} className="absolute inset-0 block w-full h-full" />
      {/* Fine grain carried by the curl flow */}
      <canvas ref={canvasRef} className="absolute inset-0 block w-full h-full" />
      {/* Subtle vignette to settle the edges of the frame */}
      <div className="absolute inset-0 bg-radial-[circle_at_center,transparent_38%,rgba(0,0,0,0.72)_100%]" />
    </div>
  );
}


