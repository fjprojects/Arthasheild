import React from "react";

/**
 * ArthaShield Design System — Tooltip
 *
 * A CSS-only tooltip: no animation library, no portal, no positioning engine.
 * The bubble is presentational (it is hidden from assistive technology) and the
 * trigger keeps its own accessible name, so a screen reader is never given a
 * duplicate or a floating fragment of text.
 *
 * The class list is built here rather than through the shared `cn` helper:
 * the UI kit pulls in `tailwind-merge`, which is not worth its weight for a
 * component this small.
 */
export function Tooltip({
  children,
  label,
  side = "right",
  className = "",
  ...props
}) {
  if (!label) {
    return <>{children}</>;
  }

  const position =
    side === "right" ? "left-full ml-2" : "right-full mr-2";

  return (
    <span
      className={"relative block group/tooltip " + className}
      {...props}
    >
      {children}
      <span
        aria-hidden="true"
        className={
          "pointer-events-none absolute top-1/2 -translate-y-1/2 z-50 " +
          "whitespace-nowrap bg-black text-white border border-[#404040] " +
          "px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.18em] " +
          "shadow-[0_0_20px_rgba(0,0,0,0.9)] " +
          "opacity-0 translate-x-1 transition-all duration-150 ease-out " +
          "group-hover/tooltip:opacity-100 group-hover/tooltip:translate-x-0 " +
          "group-focus-within/tooltip:opacity-100 group-focus-within/tooltip:translate-x-0 " +
          position
        }
      >
        {label}
      </span>
    </span>
  );
}

export default Tooltip;
