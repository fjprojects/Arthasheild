import React from "react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Card Component Primitives
 * Adapted from LabTwin component architecture with dark fintech visual tokens.
 */
export function Card({
  children,
  variant = "default",
  className = "",
  highlight = false,
  ...props
}) {
  const variantStyles = {
    default:
      "bg-slate-900/60 border border-slate-800/80 text-slate-100 shadow-lg shadow-black/20",
    elevated:
      "bg-slate-900/90 border border-slate-800 text-slate-100 shadow-xl shadow-black/40",
    glass:
      "bg-slate-950/60 border border-slate-800/60 backdrop-blur-md text-slate-100 shadow-md",
    interactive:
      "bg-slate-900/60 border border-slate-800/80 hover:border-slate-700/80 hover:bg-slate-900/80 transition-all duration-200 cursor-pointer text-slate-100 shadow-md",
    highlight:
      "bg-gradient-to-b from-slate-900/90 to-emerald-950/20 border border-emerald-500/30 text-slate-100 shadow-xl shadow-emerald-950/20",
    danger:
      "bg-gradient-to-b from-slate-900/90 to-rose-950/20 border border-rose-500/30 text-slate-100 shadow-xl shadow-rose-950/20",
    terminal:
      "bg-slate-950 border border-slate-800 text-slate-200 font-mono shadow-inner shadow-black/50",
  };

  const effectiveVariant = highlight ? "highlight" : variant;

  return (
    <div
      className={cn(
        "rounded-2xl p-6 transition-all duration-150",
        variantStyles[effectiveVariant] || variantStyles.default,
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className = "", border = true, ...props }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 pb-4 mb-4",
        border && "border-b border-slate-800/70",
        className
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
        "text-base font-bold tracking-tight text-white m-0 flex items-center justify-between",
        className
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
      className={cn("text-xs text-slate-400 leading-relaxed m-0", className)}
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

export function CardFooter({ children, className = "", ...props }) {
  return (
    <div
      className={cn(
        "pt-4 mt-4 border-t border-slate-800/60 flex items-center justify-between text-xs text-slate-400",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export default Card;

