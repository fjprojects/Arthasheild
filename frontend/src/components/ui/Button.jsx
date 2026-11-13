import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Monochrome Button Component
 * Features strict black, white, silver & charcoal styling with venom-flash reaction support.
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
    "interactive-control inline-flex items-center justify-center font-mono font-medium tracking-tight cursor-pointer select-none disabled:opacity-35 disabled:cursor-not-allowed disabled:pointer-events-none uppercase";

  const sizeStyles = {
    sm: "px-2.5 py-1 text-[11px] gap-1.5",
    md: "px-4 py-2 text-xs gap-2",
    lg: "px-6 py-2.5 text-sm gap-2.5 font-bold tracking-wider",
    icon: "p-2 aspect-square",
  };

  const variantStyles = {
    primary:
      "bg-white hover:bg-zinc-200 text-black font-bold border border-white shadow-[0_0_15px_rgba(255,255,255,0.15)] hover:shadow-[0_0_22px_rgba(255,255,255,0.35)]",
    secondary:
      "bg-[#111111] hover:bg-[#202020] text-white border border-[#202020] hover:border-[#AAAAAA]",
    outline:
      "bg-transparent hover:bg-white text-white hover:text-black border border-[#AAAAAA] hover:border-white shadow-sm",
    ghost:
      "bg-transparent hover:bg-[#111111] text-[#AAAAAA] hover:text-white border border-transparent",
    danger:
      "bg-black hover:bg-white text-white hover:text-black border border-white font-bold tracking-wider",
    accent:
      "bg-[#202020] hover:bg-white text-white hover:text-black border border-zinc-700 hover:border-white",
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
