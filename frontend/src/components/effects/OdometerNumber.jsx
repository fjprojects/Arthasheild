import React, { useState, useEffect } from 'react';

/**
 * DigitColumn
 * Displays a vertical column of 0-9 and rolls to target digit.
 */
function DigitColumn({ digit }) {
  const num = parseInt(digit, 10);
  const isNumber = !isNaN(num);

  if (!isNumber) {
    return <span className="inline-block px-0.5">{digit}</span>;
  }

  return (
    <span 
      className="inline-block relative overflow-hidden h-[1em] leading-[1em] text-center"
      style={{ width: '0.62em' }}
    >
      <span
        className="flex flex-col transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{ transform: `translateY(-${num * 10}%)` }}
      >
        {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
          <span key={n} className="h-[1em] leading-[1em] flex items-center justify-center">
            {n}
          </span>
        ))}
      </span>
    </span>
  );
}

/**
 * OdometerNumber Component
 * 
 * Takes a number or formatted string (e.g. 57, "1,200", 25)
 * and animates each digit rolling into place like a mechanical odometer.
 */
export default function OdometerNumber({ value = 0, className = '', prefix = '', suffix = '' }) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    // Slight tick delay on mount/update so the roll animation is visibly perceived
    const timer = setTimeout(() => {
      setDisplayValue(value);
    }, 60);
    return () => clearTimeout(timer);
  }, [value]);

  const chars = String(displayValue).split('');

  return (
    <span className={`inline-flex items-center font-mono select-none tracking-tight ${className}`}>
      {prefix && <span className="mr-0.5">{prefix}</span>}
      <span className="inline-flex overflow-hidden">
        {chars.map((char, idx) => (
          <DigitColumn key={`${idx}-${char}`} digit={char} />
        ))}
      </span>
      {suffix && <span className="ml-0.5">{suffix}</span>}
    </span>
  );
}

