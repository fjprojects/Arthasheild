import React from 'react';
import { usePointerSpotlight } from './motion';

/**
 * ArthaShield — Spotlight Card
 *
 * A monochrome panel that responds to the pointer in three restrained ways:
 *
 *   1. it lifts 3px,
 *   2. its border illuminates to a muted silver,
 *   3. a very soft spotlight follows the cursor.
 *
 * On pointer devices it also takes an almost imperceptible 3D tilt. Both are
 * driven entirely by CSS transitions (see `.spotlight-card` / `.tilt-card` in
 * index.css); JavaScript only publishes the pointer position as CSS custom
 * properties, so a pointer move never re-renders React.
 *
 * Touch devices and users who prefer reduced motion get the static card.
 */
export function SpotlightCard({
  children,
  className = '',
  tilt = false,
  as: Tag = 'div',
  ...props
}) {
  const { ref, tiltEnabled, handlers } = usePointerSpotlight({ tilt });

  const classes = [
    'spotlight-card',
    tiltEnabled ? 'tilt-card' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <Tag ref={ref} className={classes} {...handlers} {...props}>
      {children}
    </Tag>
  );
}

export default SpotlightCard;
