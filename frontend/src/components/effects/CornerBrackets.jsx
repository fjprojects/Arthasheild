import React from 'react';

/**
 * CornerBrackets Component
 * 
 * Renders SVG corner brackets (`┌ ┐` and `└ ┘`) that trace and draw themselves
 * in from the corners using SVG stroke-dasharray animations.
 */
export default function CornerBrackets({ 
  size = 10, 
  strokeWidth = 2, 
  color = '#FFFFFF', 
  className = '' 
}) {
  return (
    <div className={`pointer-events-none absolute inset-0 z-10 ${className}`} aria-hidden="true">
      {/* Top Left Bracket */}
      <svg
        className="absolute top-0 left-0"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        fill="none"
      >
        <path
          d={`M0 ${size} L0 0 L${size} 0`}
          stroke={color}
          strokeWidth={strokeWidth}
          className="animate-draw-bracket"
        />
      </svg>

      {/* Top Right Bracket */}
      <svg
        className="absolute top-0 right-0"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        fill="none"
      >
        <path
          d={`M0 0 L${size} 0 L${size} ${size}`}
          stroke={color}
          strokeWidth={strokeWidth}
          className="animate-draw-bracket"
        />
      </svg>

      {/* Bottom Left Bracket */}
      <svg
        className="absolute bottom-0 left-0"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        fill="none"
      >
        <path
          d={`M0 0 L0 ${size} L${size} ${size}`}
          stroke={color}
          strokeWidth={strokeWidth}
          className="animate-draw-bracket"
        />
      </svg>

      {/* Bottom Right Bracket */}
      <svg
        className="absolute bottom-0 right-0"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        fill="none"
      >
        <path
          d={`M0 ${size} L${size} ${size} L${size} 0`}
          stroke={color}
          strokeWidth={strokeWidth}
          className="animate-draw-bracket"
        />
      </svg>
    </div>
  );
}

