import React from 'react';
import { useGrowToValue, useInView } from './motion';

/**
 * ArthaShield — Progress Bar
 *
 * A monochrome bar that grows from empty the first time its data becomes
 * available and the bar is on screen.
 *
 * The underlying value is never altered: the component only controls when the
 * rendered width is released from 0 to the exact percentage it was given, so
 * the animation can never suggest that the financial amount itself is changing.
 * The observer disconnects after the first reveal, so the bar never replays
 * during later interaction.
 */
export function ProgressBar({ value, className = '' }) {
  const ready = value !== null && value !== undefined && !Number.isNaN(value);
  const [ref, inView] = useInView({ threshold: 0.35 });
  const grown = useGrowToValue(value, ready && inView);

  const target = `${Math.min(100, Math.max(0, ready ? value : 0))}%`;

  return (
    <div ref={ref} className={`h-1 w-full bg-[#111111] overflow-hidden ${className}`}>
      <div
        className={`grow-bar h-full bg-white ${grown ? 'is-ready' : ''}`}
        style={{ '--bar-target': target }}
      />
    </div>
  );
}

export default ProgressBar;
