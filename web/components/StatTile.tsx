"use client";

import { useEffect, useRef, useState } from "react";

function formatCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(0)}K`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value % 1 === 0 ? String(value) : value.toFixed(1);
}

/** Counts up to the value on change — makes a polled dashboard feel live
 *  rather than merely refreshed. Skipped when the user prefers reduced motion. */
function useCountUp(target: number, ms = 550): number {
  const [display, setDisplay] = useState(target);
  const fromRef = useRef(target);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || fromRef.current === target) {
      setDisplay(target);
      fromRef.current = target;
      return;
    }
    const from = fromRef.current;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min((now - start) / ms, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (target - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);

  return display;
}

function Sparkline({ points, color }: { points: number[]; color: string }) {
  if (points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const w = 72;
  const h = 22;
  const d = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - ((p - min) / span) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="overflow-visible" aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" opacity={0.85} />
    </svg>
  );
}

export default function StatTile({
  label,
  value,
  prefix = "",
  suffix = "",
  tone = "default",
  spark,
  hint,
}: {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  tone?: "default" | "good" | "warn" | "bad";
  spark?: number[];
  hint?: string;
}) {
  const shown = useCountUp(value);
  const toneClass = {
    default: "text-foreground",
    good: "text-good",
    warn: "text-warn",
    bad: "text-bad",
  }[tone];
  const sparkColor = {
    default: "var(--series-1)",
    good: "var(--status-good)",
    warn: "var(--status-warn)",
    bad: "var(--status-bad)",
  }[tone];

  return (
    <div className="card card-interactive p-5">
      <div className="flex items-start justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted">
          {label}
        </p>
        {spark && spark.length > 1 && <Sparkline points={spark} color={sparkColor} />}
      </div>
      <p className={`mt-3 text-[28px] font-semibold leading-none tracking-tight ${toneClass}`}>
        {prefix}
        {formatCompact(shown)}
        <span className="text-base font-normal text-muted">{suffix}</span>
      </p>
      {hint && <p className="mt-2 text-[11px] text-muted-dim">{hint}</p>}
    </div>
  );
}
