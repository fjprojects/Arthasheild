import React from "react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Monochrome Badge Component
 * Semantic financial status indicators in pure stark monochrome (SAFE, WARNING, CRITICAL, NEUTRAL, AI, MONO).
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
    SAFE: "bg-white/10 text-white border-white/40 shadow-[0_0_8px_rgba(255,255,255,0.1)]",
    SUCCESS: "bg-white/10 text-white border-white/40 shadow-[0_0_8px_rgba(255,255,255,0.1)]",
    WARNING: "bg-[#111111] text-zinc-300 border-zinc-600 border-dashed",
    CRITICAL: "bg-white text-black font-bold border-white shadow-[0_0_12px_rgba(255,255,255,0.3)]",
    DANGER: "bg-white text-black font-bold border-white shadow-[0_0_12px_rgba(255,255,255,0.3)]",
    NEUTRAL: "bg-[#111111] text-[#AAAAAA] border-[#202020]",
    DEFAULT: "bg-[#111111] text-[#AAAAAA] border-[#202020]",
    AI: "bg-[#050505] text-white border-white/60 font-mono",
    ACCENT: "bg-[#202020] text-white border-white/40",
    MONO: "bg-[#050505] text-white border-[#202020] font-mono",
    OUTLINE: "bg-transparent text-white border-zinc-700",
  };

  const dotColors = {
    SAFE: "bg-white",
    SUCCESS: "bg-white",
    WARNING: "bg-[#AAAAAA]",
    CRITICAL: "bg-black",
    DANGER: "bg-black",
    NEUTRAL: "bg-[#AAAAAA]",
    DEFAULT: "bg-[#AAAAAA]",
    AI: "bg-white",
    ACCENT: "bg-white",
    MONO: "bg-white",
    OUTLINE: "bg-white",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-[9px] gap-1 font-mono uppercase tracking-wider",
    md: "px-2.5 py-0.5 text-[10px] gap-1.5 font-mono uppercase tracking-wider",
    lg: "px-3 py-1 text-xs gap-2 font-mono uppercase font-bold tracking-wider",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center font-mono tracking-wider border select-none transition-colors",
        sizeStyles[size] || sizeStyles.md,
        variantStyles[normalizedVariant] || variantStyles.NEUTRAL,
        className
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full shrink-0",
            dotColors[normalizedVariant] || "bg-white",
            pulse && "animate-pulse"
          )}
        />
      )}
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{children}</span>
    </span>
  );
}

export default Badge;
