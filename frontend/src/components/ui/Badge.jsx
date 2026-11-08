import React from "react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Badge Component
 * Semantic financial status indicators (SAFE, WARNING, CRITICAL, NEUTRAL, AI, MONO).
 */
export function Badge({
  children,
  variant = "NEUTRAL",
  size = "md",
  dot = false,
  pulse = false,
  icon = null,
  className = "",
  ...props
}) {
  const normalizedVariant = String(variant).toUpperCase();

  const variantStyles = {
    SAFE: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
    SUCCESS: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
    WARNING: "bg-amber-500/10 text-amber-400 border-amber-500/25",
    CRITICAL: "bg-rose-500/10 text-rose-400 border-rose-500/25",
    DANGER: "bg-rose-500/10 text-rose-400 border-rose-500/25",
    NEUTRAL: "bg-slate-800/80 text-slate-300 border-slate-700/60",
    DEFAULT: "bg-slate-800/80 text-slate-300 border-slate-700/60",
    AI: "bg-indigo-500/10 text-indigo-300 border-indigo-500/25",
    ACCENT: "bg-indigo-500/10 text-indigo-300 border-indigo-500/25",
    MONO: "bg-slate-950 text-emerald-300 border-emerald-900/40 font-mono",
    OUTLINE: "bg-transparent text-slate-300 border-slate-700",
  };

  const dotColors = {
    SAFE: "bg-emerald-400",
    SUCCESS: "bg-emerald-400",
    WARNING: "bg-amber-400",
    CRITICAL: "bg-rose-400",
    DANGER: "bg-rose-400",
    NEUTRAL: "bg-slate-400",
    DEFAULT: "bg-slate-400",
    AI: "bg-indigo-400",
    ACCENT: "bg-indigo-400",
    MONO: "bg-emerald-400",
    OUTLINE: "bg-slate-400",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-[10px] gap-1 rounded-md",
    md: "px-2.5 py-1 text-xs gap-1.5 rounded-lg",
    lg: "px-3 py-1.5 text-xs gap-2 rounded-xl font-bold",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center font-semibold tracking-tight border select-none transition-colors",
        sizeStyles[size] || sizeStyles.md,
        variantStyles[normalizedVariant] || variantStyles.NEUTRAL,
        className
      )}
      {...props}
    >
      {dot && (
        <span className="relative flex h-1.5 w-1.5 shrink-0">
          {pulse && (
            <span
              className={cn(
                "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75",
                dotColors[normalizedVariant] || "bg-emerald-400"
              )}
            />
          )}
          <span
            className={cn(
              "relative inline-flex rounded-full h-1.5 w-1.5",
              dotColors[normalizedVariant] || "bg-emerald-400"
            )}
          />
        </span>
      )}
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{children}</span>
    </span>
  );
}

export default Badge;

