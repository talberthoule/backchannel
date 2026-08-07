import { useEffect, useRef } from "react";
import type { AudioLevelSource } from "../../hooks/useAudioCapture";

interface AudioIndicatorProps {
  isCapturing: boolean;
  /** Live 0-1 level read once per frame; never a React state value (ALP-291). */
  level: AudioLevelSource;
  /**
   * Accessible name. Required because more than one meter can be on screen at
   * once, and two meters sharing a name are indistinguishable to a screen
   * reader; the neighbouring visual caption is not part of the accessible name.
   */
  label: string;
}

const BAR_COUNT = 5;
const BAR_HEIGHTS = Array.from({ length: BAR_COUNT }, (_, i) => 8 + i * 3);
// Written with classList, so both literals have to stay in this file for the
// Tailwind scanner to emit them.
const ACTIVE_BAR_CLASS = "bg-green-500";
const IDLE_BAR_CLASS = "bg-brand-light-gray-1";
// Assistive tech cannot use a 60Hz meter; ~6Hz still reads as live.
const ARIA_INTERVAL_MS = 160;

function activeBarCount(level: number) {
  return level > 0.015 ? Math.max(1, Math.ceil(level * BAR_COUNT)) : 0;
}

export default function AudioIndicator({ isCapturing, level, label }: AudioIndicatorProps) {
  const meterRef = useRef<HTMLDivElement | null>(null);
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);
  const paintedBarsRef = useRef(-1);
  const paintedAriaRef = useRef(-1);
  const ariaPaintedAtRef = useRef(0);

  // The meter is the only thing in the app that changes at frame rate, so it
  // writes to its own DOM nodes instead of going through React. React commits
  // zero times per second for audio level; only isCapturing re-renders it.
  useEffect(() => {
    const paint = (now: number, force: boolean) => {
      // With no capture there is no input level, so the bars and the announced
      // value both read zero rather than whatever the source last held.
      const value = isCapturing ? Math.max(0, Math.min(1, level.current)) : 0;
      const active = activeBarCount(value);

      if (active !== paintedBarsRef.current) {
        for (let i = 0; i < BAR_COUNT; i++) {
          const bar = barsRef.current[i];
          if (!bar) continue;
          bar.classList.toggle(ACTIVE_BAR_CLASS, i < active);
          bar.classList.toggle(IDLE_BAR_CLASS, i >= active);
        }
        // Recorded only once the bars are actually painted, so a missing node
        // cannot leave the meter stuck on a paint that never happened.
        paintedBarsRef.current = active;
      }

      const aria = Math.round(value * 100);
      if (
        aria !== paintedAriaRef.current
        && (force || now - ariaPaintedAtRef.current >= ARIA_INTERVAL_MS)
      ) {
        paintedAriaRef.current = aria;
        ariaPaintedAtRef.current = now;
        meterRef.current?.setAttribute("aria-valuenow", String(aria));
      }
    };

    // Settle the meter for the current props even when nothing is capturing,
    // so stopping capture drops the bars and the announced value back to zero.
    paint(performance.now(), true);
    if (!isCapturing) return;

    let frame = requestAnimationFrame(function step(now: number) {
      paint(now, false);
      frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [isCapturing, level]);

  return (
    <div
      ref={meterRef}
      className="flex items-center gap-2"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={0}
    >
      {/* Pulsing dot */}
      <span className="relative flex h-3 w-3">
        {isCapturing && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
        )}
        <span
          className={`relative inline-flex h-3 w-3 rounded-full ${
            isCapturing ? "bg-green-500" : "bg-brand-mid-gray"
          }`}
        />
      </span>

      {/* Level meter bars: className stays constant so React never overwrites
          the classes the animation frame just wrote. */}
      <div className="flex items-end gap-0.5">
        {BAR_HEIGHTS.map((height, i) => (
          <div
            key={i}
            ref={(node) => {
              barsRef.current[i] = node;
            }}
            className={`w-1 rounded-sm transition-all duration-100 ${IDLE_BAR_CLASS}`}
            style={{ height: `${height}px` }}
          />
        ))}
      </div>

      {/* Status text */}
      <span className="font-body text-sm text-brand-gray">
        {isCapturing ? "Listening..." : "Mic off"}
      </span>
    </div>
  );
}
