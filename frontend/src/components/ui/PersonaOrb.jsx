import React, { useCallback, useEffect, useRef, useState } from 'react';
import { usePointerSpotlight } from './motion';

/**
 * ArthaShield — Orbital Persona Selector
 *
 * Three synthetic identities sit on a single silver rail. Selecting one moves
 * a glowing particle along the rail and illuminates the destination orb; the
 * actual persona change still happens through `onSelect(persona.id)`, exactly
 * as before.
 *
 * The visual selection is optimistic: clicking a node lights it immediately
 * while the parent fetches the matching dashboard payload from the API. If the
 * parent never confirms the change, the highlight falls back to the real
 * selection after a short grace period.
 *
 * Motion is CSS-driven. JavaScript only supplies the selected index, a pulse
 * key for one-shot animations, pointer position and visibility state.
 */

const CONFIRM_GRACE_MS = 5000;

function firstWord(name = '') {
  return name.split(' ')[0];
}

export function PersonaOrb({ personas = [], selectedId, onSelect }) {
  const [pendingId, setPendingId] = useState(null);
  const [pulse, setPulse] = useState({ id: null, direction: 'forward', key: 0 });
  const [live, setLive] = useState(true);
  const nodesRef = useRef([]);
  const previousIndexRef = useRef(null);
  const { ref: rootRef, handlers: spotlightHandlers } = usePointerSpotlight();

  const count = personas.length;
  const resolvedId = pendingId || selectedId;
  const selectedIndex = personas.findIndex((persona) => persona.id === resolvedId);
  // The visual track keeps a stable position before the first persona arrives.
  const visualIndex = selectedIndex >= 0 ? selectedIndex : 0;
  const selectedPersona = selectedIndex >= 0 ? personas[selectedIndex] : null;

  // If the API call fails, never leave the selector showing a persona that was
  // not actually loaded. A confirmed selection resolves naturally through
  // `selectedId`, so no extra state-sync render is needed on success.
  useEffect(() => {
    if (!pendingId) return undefined;
    const timer = window.setTimeout(() => setPendingId(null), CONFIRM_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [pendingId]);

  // Fire the travel pulse once per real index change (not on initial mount).
  useEffect(() => {
    if (!count) {
      previousIndexRef.current = null;
      return;
    }
    if (selectedIndex < 0) return;
    const previous = previousIndexRef.current;
    previousIndexRef.current = selectedIndex;
    if (previous === null || previous === selectedIndex) return;
    setPulse((current) => ({
      id: personas[selectedIndex].id,
      direction: selectedIndex > previous ? 'forward' : 'reverse',
      key: current.key + 1,
    }));
  }, [count, personas, selectedIndex]);

  // Pause looping CSS animations when the tab or the navbar module is hidden.
  useEffect(() => {
    const node = rootRef.current;
    if (!node) return undefined;

    const visibility = { intersecting: true };
    const sync = () => setLive(visibility.intersecting && !document.hidden);

    let observer = null;
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(
        (entries) => {
          const entry = entries[entries.length - 1];
          if (!entry) return;
          visibility.intersecting = entry.isIntersecting;
          sync();
        },
        { threshold: 0 },
      );
      observer.observe(node);
    }

    document.addEventListener('visibilitychange', sync);
    sync();

    return () => {
      if (observer) observer.disconnect();
      document.removeEventListener('visibilitychange', sync);
    };
  }, [rootRef]);

  const selectPersona = useCallback(
    (persona) => {
      if (!persona) return;
      setPendingId(persona.id);
      onSelect?.(persona.id);
    },
    [onSelect],
  );

  const handleKeyDown = useCallback(
    (event, index) => {
      if (!count) return;
      let next = null;

      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        next = (index + 1) % count;
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        next = (index - 1 + count) % count;
      } else if (event.key === 'Home') {
        next = 0;
      } else if (event.key === 'End') {
        next = count - 1;
      }

      if (next === null) return;
      event.preventDefault();
      nodesRef.current[next]?.focus();
      selectPersona(personas[next]);
    },
    [count, personas, selectPersona],
  );

  if (!count) return null;

  const indexLabel = selectedIndex >= 0
    ? String(selectedIndex + 1).padStart(2, '0')
    : '—';
  const particleLeft = `${((visualIndex + 0.5) / count) * 100}%`;

  return (
    <div
      ref={rootRef}
      {...spotlightHandlers}
      className="persona-orbit"
      data-live={live ? 'true' : 'false'}
    >
      <span className="persona-orbit__corner persona-orbit__corner--tl" aria-hidden="true" />
      <span className="persona-orbit__corner persona-orbit__corner--tr" aria-hidden="true" />
      <span className="persona-orbit__corner persona-orbit__corner--bl" aria-hidden="true" />
      <span className="persona-orbit__corner persona-orbit__corner--br" aria-hidden="true" />

      <div className="persona-orbit__meta" aria-hidden="true">
        <span className="persona-orbit__meta-label">
          <span className="persona-orbit__meta-dot" />
          Synthetic persona
        </span>
        <span className="persona-orbit__meta-index">
          {indexLabel} / {String(count).padStart(2, '0')}
        </span>
      </div>

      <div className="persona-orbit__field">
        <div
          className="persona-orbit__rail"
          style={{ left: `${50 / count}%`, right: `${50 / count}%` }}
          aria-hidden="true"
        >
          <span className="persona-orbit__rail-base" />
          {pulse.key > 0 && (
            <span
              key={pulse.key}
              className={`persona-orbit__sweep is-${pulse.direction}`}
            />
          )}
        </div>

        <span
          className="persona-orbit__particle"
          style={{ left: particleLeft }}
          data-ready={selectedIndex >= 0 ? 'true' : 'false'}
          aria-hidden="true"
        />

        <div
          className="persona-orbit__nodes"
          role="radiogroup"
          aria-label="Synthetic persona"
          aria-orientation="horizontal"
          style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}
        >
          {personas.map((persona, index) => {
            const isSelected = persona.id === resolvedId;
            const isTabStop = isSelected || (selectedIndex < 0 && index === 0);
            return (
              <button
                key={persona.id}
                ref={(element) => {
                  nodesRef.current[index] = element;
                }}
                type="button"
                role="radio"
                aria-checked={isSelected}
                tabIndex={isTabStop ? 0 : -1}
                onClick={() => selectPersona(persona)}
                onKeyDown={(event) => handleKeyDown(event, index)}
                data-pulse={pulse.id === persona.id && pulse.key > 0 ? 'true' : 'false'}
                className="persona-node"
                title={persona.name}
              >
                <span className="persona-orb" aria-hidden="true">
                  <span className="persona-orb__halo" />
                  <span className="persona-orb__ring" />
                  <span className="persona-orb__shell">
                    <span className="persona-orb__reflection" />
                    <span className="persona-orb__scan" />
                  </span>
                  <span className="persona-orb__core" />
                </span>
                <span className="persona-node__label">{firstWord(persona.name)}</span>
              </button>
            );
          })}
        </div>
      </div>

      <span className="sr-only" aria-live="polite">
        {selectedPersona ? `${selectedPersona.name} selected` : ''}
      </span>
    </div>
  );
}

export default PersonaOrb;
