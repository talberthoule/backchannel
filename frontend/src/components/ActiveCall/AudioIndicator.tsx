import { useMemo } from "react";

interface AudioIndicatorProps {
  isCapturing: boolean;
  audioLevel: number;
}

export default function AudioIndicator({ isCapturing, audioLevel }: AudioIndicatorProps) {
  const bars = useMemo(() => {
    const count = 5;
    const level = Math.max(0, Math.min(1, audioLevel));
    const activeCount = level > 0.015 ? Math.max(1, Math.ceil(level * count)) : 0;
    return Array.from({ length: count }, (_, i) => i < activeCount);
  }, [audioLevel]);

  return (
    <div
      className="flex items-center gap-2"
      role="meter"
      aria-label="Microphone input level"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(audioLevel * 100)}
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

      {/* Level meter bars */}
      <div className="flex items-end gap-0.5">
        {bars.map((active, i) => (
          <div
            key={i}
            className={`w-1 rounded-sm transition-all duration-100 ${
              isCapturing && active
                ? "bg-green-500"
                : "bg-brand-light-gray-1"
            }`}
            style={{ height: `${8 + i * 3}px` }}
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
