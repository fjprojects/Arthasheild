import React, { forwardRef } from "react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Monochrome Input Component Primitive
 * High-contrast dark fintech styled input with accessible states and zero color.
 */
export const Input = forwardRef(function Input(
  {
    className = "",
    error = false,
    type = "text",
    leftAddon = null,
    rightAddon = null,
    disabled = false,
    ...props
  },
  ref
) {
  const hasAddon = leftAddon || rightAddon;

  const inputElement = (
    <input
      ref={ref}
      type={type}
      disabled={disabled}
      aria-invalid={Boolean(error)}
      className={cn(
        "w-full bg-[#050505] border text-xs text-white placeholder:text-zinc-600 font-mono transition-all duration-150",
        "focus:outline-none focus:ring-1",
        error
          ? "border-white focus:border-white focus:ring-white text-white"
          : "border-[#202020] focus:border-white focus:ring-white",
        disabled && "opacity-40 cursor-not-allowed bg-black",
        hasAddon ? "bg-transparent border-0 focus:ring-0 p-0" : "px-3.5 py-2",
        className
      )}
      {...props}
    />
  );

  if (!hasAddon) {
    return inputElement;
  }

  return (
    <div
      className={cn(
        "flex items-center w-full bg-[#050505] border px-3 py-2 text-xs font-mono transition-all duration-150",
        "focus-within:ring-1",
        error
          ? "border-white focus-within:border-white focus-within:ring-white"
          : "border-[#202020] focus-within:border-white focus-within:ring-white",
        disabled && "opacity-40 cursor-not-allowed bg-black",
        className
      )}
    >
      {leftAddon && <span className="mr-2 text-[#AAAAAA] shrink-0 font-mono">{leftAddon}</span>}
      {inputElement}
      {rightAddon && <span className="ml-2 text-[#AAAAAA] shrink-0 font-mono">{rightAddon}</span>}
    </div>
  );
});

export default Input;
