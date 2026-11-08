import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Button Component
 * Adapted from LabTwin component architecture with dark fintech visual tokens.
 */
export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  disabled = false,
  loading = false,
  leftIcon = null,
  rightIcon = null,
  onClick,
  type = "button",
  ...props
}) {
  const baseStyles =
    "inline-flex items-center justify-center font-semibold tracking-tight transition-all duration-150 cursor-pointer select-none active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/80 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:opacity-45 disabled:cursor-not-allowed disabled:pointer-events-none disabled:active:scale-100";

  const sizeStyles = {
    sm: "px-2.5 py-1 text-xs gap-1.5 rounded-lg",
    md: "px-3.5 py-2 text-xs gap-2 rounded-xl",
    lg: "px-5 py-2.5 text-sm gap-2.5 rounded-xl font-bold",
    icon: "p-2 rounded-xl aspect-square",
  };

  const variantStyles = {
    primary:
      "bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold border border-emerald-400/30 shadow-md shadow-emerald-500/15 hover:shadow-emerald-500/25",
    secondary:
      "bg-slate-900/90 hover:bg-slate-800 text-slate-200 border border-slate-800 hover:border-slate-700 shadow-sm",
    outline:
      "bg-transparent hover:bg-slate-800/60 text-slate-300 hover:text-white border border-slate-700 hover:border-slate-600",
    ghost:
      "bg-transparent hover:bg-slate-800/60 text-slate-400 hover:text-slate-100 border border-transparent",
    danger:
      "bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 hover:text-rose-300 border border-rose-500/30 hover:border-rose-500/50 shadow-sm shadow-rose-950/40",
    accent:
      "bg-indigo-600 hover:bg-indigo-500 text-white font-bold border border-indigo-400/30 shadow-md shadow-indigo-600/20 hover:shadow-indigo-600/30",
  };

  return (
    <button
      type={type}
      disabled={disabled || loading}
      onClick={onClick}
      className={cn(
        baseStyles,
        sizeStyles[size] || sizeStyles.md,
        variantStyles[variant] || variantStyles.primary,
        className
      )}
      {...props}
    >
      {loading ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
      ) : (
        leftIcon && <span className="shrink-0">{leftIcon}</span>
      )}
      <span>{children}</span>
      {!loading && rightIcon && <span className="shrink-0">{rightIcon}</span>}
    </button>
  );
}

export default Button;

