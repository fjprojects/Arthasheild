import React, { forwardRef } from "react";
import { cn } from "./utils";

/**
 * ArthaShield Design System — Input Component Primitive
 * Dark fintech styled input with accessible states.
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
        "w-full bg-slate-950 border text-xs text-white placeholder:text-slate-500 transition-all duration-150",
        "focus:outline-none focus:ring-1",
        error
          ? "border-rose-500/80 focus:border-rose-500 focus:ring-rose-500 text-rose-100"
          : "border-slate-800 focus:border-emerald-500 focus:ring-emerald-500",
        disabled && "opacity-50 cursor-not-allowed bg-slate-900/50",
        hasAddon ? "bg-transparent border-0 focus:ring-0 p-0" : "rounded-xl px-3.5 py-2",
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
        "flex items-center w-full bg-slate-950 border rounded-xl px-3 py-2 text-xs transition-all duration-150",
        "focus-within:ring-1",
        error
          ? "border-rose-500/80 focus-within:border-rose-500 focus-within:ring-rose-500"
          : "border-slate-800 focus-within:border-emerald-500 focus-within:ring-emerald-500",
        disabled && "opacity-50 cursor-not-allowed bg-slate-900/50",
        className
      )}
    >
      {leftAddon && <span className="mr-2 text-slate-400 shrink-0">{leftAddon}</span>}
      {inputElement}
      {rightAddon && <span className="ml-2 text-slate-400 shrink-0">{rightAddon}</span>}
    </div>
  );
});

/**
 * Accessible FormField Wrapper with label, badge, helper text and error message.
 */
export function FormField({
  id,
  label,
  badge = null,
  error = null,
  helperText = null,
  children,
  className = "",
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <div className="flex items-center justify-between text-xs">
          <label htmlFor={id} className="font-semibold text-slate-300">
            {label}
          </label>
          {badge && <div>{badge}</div>}
        </div>
      )}
      {children}
      {error ? (
        <p className="text-[11px] text-rose-400 font-medium">{error}</p>
      ) : helperText ? (
        <p className="text-[11px] text-slate-400">{helperText}</p>
      ) : null}
    </div>
  );
}

/**
 * Textarea primitive for bank statements, contracts, or prompt text.
 */
export const Textarea = forwardRef(function Textarea(
  { className = "", error = false, disabled = false, rows = 6, ...props },
  ref
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      disabled={disabled}
      aria-invalid={Boolean(error)}
      className={cn(
        "w-full bg-slate-950 border rounded-xl p-3.5 text-xs text-slate-200 placeholder:text-slate-500 leading-relaxed font-mono transition-all duration-150 resize-y",
        "focus:outline-none focus:ring-1",
        error
          ? "border-rose-500/80 focus:border-rose-500 focus:ring-rose-500 text-rose-100"
          : "border-slate-800 focus:border-emerald-500 focus:ring-emerald-500",
        disabled && "opacity-50 cursor-not-allowed bg-slate-900/50",
        className
      )}
      {...props}
    />
  );
});

export default Input;

