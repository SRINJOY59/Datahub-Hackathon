"use client";

// Time-series line chart built to the dataviz skill's mark specs:
// 2px line with round joins, ≥8px end markers carrying a 2px surface ring so
// they stay legible where they overlap, hairline solid gridlines one step off
// the surface, and a hover crosshair + tooltip (the default for line forms).
// One series per chart, so there is no legend box — the card title names what
// is plotted, and a single-swatch legend would just restate it.

import { useState } from "react";

export interface Point {
  label: string;
  value: number;
}

const W = 640;
const H = 180;
const PAD = { top: 16, right: 16, bottom: 26, left: 44 };

function niceTicks(max: number, count = 4, integer = false): number[] {
  if (max <= 0) return integer ? [0, 1] : [0, 1];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  let step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  // A count axis must not produce fractional steps: with max=1 the natural
  // step is 0.25, and an integer formatter renders those as "0 0 1 1 1" —
  // duplicate labels that misstate the scale.
  if (integer) step = Math.max(1, Math.ceil(step));
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  return ticks;
}

export default function LineChart({
  data,
  color = "var(--series-1)",
  format = (v: number) => String(Math.round(v * 10) / 10),
  emptyMessage = "No data yet",
  integer = false,
}: {
  data: Point[];
  color?: string;
  format?: (v: number) => string;
  emptyMessage?: string;
  /** Force whole-number axis ticks — for counts, where a fractional step
   * would render as duplicate labels. */
  integer?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (data.length === 0) {
    return (
      <div
        className="flex h-[180px] items-center justify-center rounded-lg text-sm"
        style={{ background: "var(--chart-surface)", color: "var(--muted)" }}
      >
        {emptyMessage}
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.value), 0);
  const ticks = niceTicks(maxValue, 4, integer);
  const yMax = ticks[ticks.length - 1] || 1;

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  // A single point has no span to divide across; centre it instead of dividing by zero.
  const x = (i: number) =>
    data.length === 1 ? PAD.left + plotW / 2 : PAD.left + (i / (data.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;

  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(d.value)}`).join(" ");
  const areaPath = `${path} L${x(data.length - 1)},${PAD.top + plotH} L${x(0)},${PAD.top + plotH} Z`;

  return (
    <div className="relative rounded-lg" style={{ background: "var(--chart-surface)" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        onMouseLeave={() => setHover(null)}
        role="img"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)}
              stroke="var(--chart-gridline)" strokeWidth={1}
            />
            <text
              x={PAD.left - 8} y={y(t) + 3} textAnchor="end"
              fontSize={10} fill="var(--muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {format(t)}
            </text>
          </g>
        ))}

        <path d={areaPath} fill={color} opacity={0.1} />
        <path
          d={path} fill="none" stroke={color} strokeWidth={2}
          strokeLinejoin="round" strokeLinecap="round"
        />

        {data.map((d, i) => (
          <circle
            key={i} cx={x(i)} cy={y(d.value)} r={hover === i ? 5 : 4}
            fill={color} stroke="var(--chart-surface)" strokeWidth={2}
          />
        ))}

        {hover !== null && (
          <line
            x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH}
            stroke="var(--chart-baseline)" strokeWidth={1}
          />
        )}

        {data.map((d, i) => (
          <rect
            key={`hit-${i}`}
            x={x(i) - plotW / Math.max(data.length, 1) / 2}
            y={PAD.top}
            width={Math.max(plotW / Math.max(data.length, 1), 12)}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}

        {data.map((d, i) =>
          i === 0 || i === data.length - 1 || data.length <= 7 ? (
            <text
              key={`lbl-${i}`} x={x(i)} y={H - 8} textAnchor="middle"
              fontSize={10} fill="var(--muted)"
            >
              {d.label.slice(5)}
            </text>
          ) : null,
        )}
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute rounded-md border border-border px-2 py-1 text-xs shadow-lg"
          style={{
            background: "var(--surface-raised)",
            left: `${(x(hover) / W) * 100}%`,
            top: 4,
            transform: "translateX(-50%)",
          }}
        >
          <span className="text-muted">{data[hover].label}</span>{" "}
          <span className="font-medium">{format(data[hover].value)}</span>
        </div>
      )}
    </div>
  );
}
