import React from "react";
import { cn } from "./utils";
import SpotlightCard from "./SpotlightCard";
import CornerBrackets from "../effects/CornerBrackets";

/**
 * ArthaShield Design System — Dashboard Card
 *
 * One premium surface for every primary dashboard panel.
 *
 * The motion engine is SpotlightCard (the stronger of the two implementations
 * compared during the design pass): the pointer position is published as CSS
 * custom properties, the spotlight and gradient border are painted by CSS, and
 * tilt is opt-in and disabled for touch/reduced-motion users. This component
 * adds the canonical surface, spacing and the two drafting accents used across
 * the product (corner brackets and the small "+" marker) so pages no longer
 * hand-roll their own card chrome.
 *
 * Layout is never imposed beyond the surface: callers keep their own grid,
 * padding and content structure through `className`.
 *
 *   <Card corners={10} marker className="p-6 space-y-4">
 *     ...
 *   </Card>
 */
const VARIANT_CLASSES = {
  default: "border-[#202020] shadow-[0_10px_30px_-26px_rgba(0,0,0,0.95)]",
  elevated: "border-[#2A2A2A] shadow-[0_18px_40px_-28px_rgba(0,0,0,0.95)]",
  glass: "border-[#202020] backdrop-blur-xl shadow-[0_10px_30px_-26px_rgba(0,0,0,0.95)]",
  flat: "border-[#202020] shadow-none",
};

/**
 * The surface tone is passed to CSS as a custom property so the spotlight
 * layer can sit above it without either one fighting the other. The values
 * match the Tailwind defaults below for non-interactive surfaces.
 */
const VARIANT_BG = {
  default: "rgba(10, 10, 10, 0.95)",
  elevated: "rgba(17, 17, 17, 0.96)",
  glass: "rgba(0, 0, 0, 0.60)",
  flat: "rgba(7, 7, 7, 1)",
};

export function Card({
  children,
  className = "",
  variant = "default",
  interactive = true,
  tilt = false,
  as: Tag = "div",
  highlight = false,
  cornerMarked = false,
  corners = false,
  cornerStroke = 1.5,
  marker = false,
  style,
  ...props
}) {
  const variantClasses = VARIANT_CLASSES[variant] || VARIANT_CLASSES.default;
  const variantBg = VARIANT_BG[variant] || VARIANT_BG.default;

  const classes = cn(
    // Canonical resting surface shared by every primary dashboard panel.
    "ash-card relative border bg-[#0A0A0A]/95 p-6 text-white",
    variantClasses,
    highlight &&
      "border-white shadow-[0_0_24px_rgba(255,255,255,0.08)]",
    cornerMarked && "corner-marked",
    marker && "group",
    className,
  );

  const content = (
    <>
      {corners ? (
        <CornerBrackets
          size={typeof corners === "number" ? corners : 10}
          strokeWidth={cornerStroke}
        />
      ) : null}
      {marker ? (
        <span
          className="absolute top-1 right-2 text-[8px] font-mono text-[#767676] transition-colors group-hover:text-white"
          aria-hidden="true"
        >
          +
        </span>
      ) : null}
      {children}
    </>
  );

  if (interactive) {
    return (
      <SpotlightCard
        as={Tag}
        tilt={tilt}
        className={classes}
        style={{ "--card-bg": variantBg, ...style }}
        {...props}
      >
        {content}
      </SpotlightCard>
    );
  }

  return (
    <Tag className={classes} style={style} {...props}>
      {content}
    </Tag>
  );
}

export function CardHeader({ children, className = "", border = true, ...props }) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3",
        border && "border-b border-[#202020] pb-4",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, className = "", as: Component = "h3", ...props }) {
  return (
    <Component
      className={cn(
        "flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-white m-0 font-mono",
        className,
      )}
      {...props}
    >
      {children}
    </Component>
  );
}

export function CardDescription({ children, className = "", ...props }) {
  return (
    <p
      className={cn(
        "text-[11px] leading-relaxed text-[#AAAAAA] m-0 font-mono",
        className,
      )}
      {...props}
    >
      {children}
    </p>
  );
}

export function CardContent({ children, className = "", ...props }) {
  return (
    <div className={cn("space-y-4", className)} {...props}>
      {children}
    </div>
  );
}

export function CardFooter({ children, className = "", border = true, ...props }) {
  return (
    <div
      className={cn(
        "flex items-center justify-between pt-4 mt-4",
        border && "border-t border-[#202020]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export default Card;
