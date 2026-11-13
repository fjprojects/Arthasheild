import React from 'react';

/**
 * TargetLock Component
 * 
 * Micro-interaction wrapper for buttons:
 * Thin crosshairs slightly outside the button border slide and snap inward
 * upon hover to simulate a terminal target acquisition lock.
 */
export default function TargetLock({ children, className = '' }) {
  return (
    <div className={`target-lock-wrap ${className}`}>
      <span className="target-crosshair target-tl" aria-hidden="true" />
      <span className="target-crosshair target-tr" aria-hidden="true" />
      <span className="target-crosshair target-bl" aria-hidden="true" />
      <span className="target-crosshair target-br" aria-hidden="true" />
      {children}
    </div>
  );
}

