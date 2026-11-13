import React, { useState, useEffect, useRef } from 'react';

const GLYPHS = 'X9$2.A1%#*0!&0148729ABCDEF_₹◈◇⟡';

/**
 * CrypticText Component
 * 
 * Provides:
 * 1. Cryptographic Scramble: Rapidly cycles through random glyphs for ~0.45s
 *    before locking into the target string character-by-character from left to right.
 * 2. Typewriter: Types out character-by-character with a blinking terminal block cursor █.
 */
export default function CrypticText({ 
  text = '', 
  mode = 'scramble', // 'scramble' | 'typewriter' | 'none'
  duration = 450, 
  speed = 22, 
  className = '',
  revealCursor = true,
  triggerKey = null // optional key to re-trigger scramble on value updates
}) {
  const targetStr = String(text ?? '');
  const [displayText, setDisplayText] = useState(targetStr);
  const [isTyping, setIsTyping] = useState(false);
  const animRef = useRef(null);

  useEffect(() => {
    if (mode === 'none' || !targetStr) {
      setDisplayText(targetStr);
      return;
    }

    if (mode === 'typewriter') {
      setIsTyping(true);
      let idx = 0;
      setDisplayText('');

      const interval = setInterval(() => {
        idx++;
        setDisplayText(targetStr.slice(0, idx));
        if (idx >= targetStr.length) {
          clearInterval(interval);
          setIsTyping(false);
        }
      }, speed);

      return () => clearInterval(interval);
    }

    // Default: Cryptographic Decryption Scramble
    let startTime = performance.now();
    const len = targetStr.length;

    const frame = (now) => {
      const elapsed = now - startTime;
      const progress = Math.min(1, elapsed / duration);
      const lockedCharsCount = Math.floor(progress * len);

      let scrambled = '';
      for (let i = 0; i < len; i++) {
        if (i < lockedCharsCount) {
          scrambled += targetStr[i];
        } else if (targetStr[i] === ' ' || targetStr[i] === ',' || targetStr[i] === '.' || targetStr[i] === '₹') {
          scrambled += targetStr[i];
        } else {
          scrambled += GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
        }
      }

      setDisplayText(scrambled);

      if (progress < 1) {
        animRef.current = requestAnimationFrame(frame);
      } else {
        setDisplayText(targetStr);
      }
    };

    animRef.current = requestAnimationFrame(frame);

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [targetStr, mode, duration, speed, triggerKey]);

  return (
    <span className={`inline-flex items-center font-mono ${className}`}>
      <span>{displayText}</span>
      {mode === 'typewriter' && isTyping && revealCursor && (
        <span className="blinking-cursor" aria-hidden="true" />
      )}
    </span>
  );
}

