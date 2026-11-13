import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Shared micro-interaction helpers for the ArthaShield interface.
 *
 * Everything here is deliberately small and DOM-first: the animated result is
 * produced by CSS transitions (see index.css), and JavaScript only supplies the
 * values CSS cannot know - a pointer position, a visibility flag, a device
 * capability.
 */

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const COARSE_POINTER_QUERY = '(pointer: coarse)';

/** True when the user asked the system to reduce motion. */
export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia(REDUCED_MOTION_QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const onChange = (event) => setReduced(event.matches);
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', onChange);
      return () => query.removeEventListener('change', onChange);
    }
    query.addListener(onChange);
    return () => query.removeListener(onChange);
  }, []);

  return reduced;
}

/** True on touch-first devices, where pointer tilt and hover do not apply. */
export function useCoarsePointer() {
  const [coarse, setCoarse] = useState(() => {
    if (typeof window === 'undefined') return false;
    if (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0) return true;
    if (!window.matchMedia) return false;
    return window.matchMedia(COARSE_POINTER_QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const query = window.matchMedia(COARSE_POINTER_QUERY);
    const onChange = (event) => setCoarse(event.matches);
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', onChange);
      return () => query.removeEventListener('change', onChange);
    }
    query.addListener(onChange);
    return () => query.removeListener(onChange);
  }, []);

  return coarse;
}

/**
 * Reports whether the element has entered the viewport.
 *
 * The observer disconnects after the first intersection, so a one-shot
 * entrance animation never replays during later UI interaction.
 */
export function useInView({ threshold = 0.2, rootMargin = '0px 0px -10% 0px', once = true } = {}) {
  const ref = useRef(null);
  // Without IntersectionObserver the element is simply treated as visible.
  const [inView, setInView] = useState(
    () => typeof IntersectionObserver === 'undefined',
  );

  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    if (typeof IntersectionObserver === 'undefined') return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setInView(true);
            if (once) observer.disconnect();
          } else if (!once) {
            setInView(false);
          }
        });
      },
      { threshold, rootMargin },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [threshold, rootMargin, once]);

  return [ref, inView];
}

/**
 * Publishes the pointer position over an element as CSS custom properties
 * (`--spot-x`, `--spot-y`) and, optionally, a very small 3D tilt
 * (`--tilt-x`, `--tilt-y`).
 *
 * The values are written straight to the DOM node, so a pointer move never
 * triggers a React render. The tilt is disabled for touch devices and for
 * users who prefer reduced motion.
 */
export function usePointerSpotlight({ tilt = false, maxTilt = 3 } = {}) {
  const ref = useRef(null);
  const frameRef = useRef(null);
  const reduced = usePrefersReducedMotion();
  const coarse = useCoarsePointer();
  const tiltEnabled = tilt && !reduced && !coarse;

  const apply = useCallback(
    (event) => {
      // Reduced motion removes the pointer spotlight entirely, not just the
      // tilt: the card stays a completely static surface.
      if (reduced) return;
      const element = ref.current;
      if (!element) return;
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      element.style.setProperty('--spot-x', `${x}px`);
      element.style.setProperty('--spot-y', `${y}px`);
      if (tiltEnabled) {
        const rotateY = ((x / rect.width) * 2 - 1) * maxTilt;
        const rotateX = ((y / rect.height) * 2 - 1) * -maxTilt;
        element.style.setProperty('--tilt-x', `${rotateX.toFixed(2)}deg`);
        element.style.setProperty('--tilt-y', `${rotateY.toFixed(2)}deg`);
      }
    },
    [reduced, tiltEnabled, maxTilt],
  );

  const onPointerMove = useCallback(
    (event) => {
      if (reduced) return;
      if (event.pointerType && event.pointerType !== 'mouse') return;
      if (frameRef.current) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        apply(event);
      });
    },
    [apply, reduced],
  );

  const onPointerLeave = useCallback(() => {
    const element = ref.current;
    if (!element) return;
    element.style.setProperty('--spot-x', '50%');
    element.style.setProperty('--spot-y', '50%');
    element.style.setProperty('--tilt-x', '0deg');
    element.style.setProperty('--tilt-y', '0deg');
  }, []);

  useEffect(
    () => () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  return {
    ref,
    tiltEnabled,
    handlers: {
      onPointerMove,
      onPointerLeave,
    },
  };
}

/**
 * Grows a value from zero once it becomes available, so a progress bar
 * animates the first time its data arrives. The value itself is never
 * altered - only the rendered width changes.
 */
export function useGrowToValue(value, ready = true) {
  const [grown, setGrown] = useState(false);
  const frameRef = useRef(null);

  useEffect(() => {
    if (!ready) return undefined;
    // Two frames: the first commits the empty bar, the second releases the
    // target width so the CSS transition can run.
    const first = requestAnimationFrame(() => {
      frameRef.current = requestAnimationFrame(() => setGrown(true));
    });
    return () => {
      cancelAnimationFrame(first);
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [ready]);

  return grown;
}
