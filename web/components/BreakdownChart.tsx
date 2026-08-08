"use client";

// Horizontal bar chart, incident count by change type. Per the dataviz
// skill's mark spec: bars capped at 24px thick with air around them, 4px
// rounded data-end (square at the baseline), a 2px surface gap between
// bars, hairline recessive gridline at zero, value labeled at the tip.
// Each bar is directly labeled with its own category, so this needs no
// separate legend box — the row label IS the identity channel.

import type { ChangeTypeCount } from "@/lib/types";

const SERIES = [
  "var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
  "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)",
];

export default function BreakdownChart({ data }: { data: ChangeTypeCount[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted">
        No incidents recorded yet
      </div>
    );
  }

  const max = Math.max(...data.map((d) => d.count));

  return (
    <div
      className="rounded-lg p-4"
      style={{ background: "var(--chart-surface)" }}
    >
      <div className="space-y-2.5">
        {data.map((d, i) => {
          const pct = max > 0 ? (d.count / max) * 100 : 0;
          return (
            <div key={d.changeType} className="flex items-center gap-3">
              <span
                className="w-36 shrink-0 truncate text-right text-xs"
                style={{ color: "var(--chart-ink-secondary)" }}
                title={d.changeType}
              >
                {d.changeType.replace(/_/g, " ")}
              </span>
              <div
                className="relative h-4 flex-1 rounded-sm"
                style={{ background: "var(--chart-gridline)" }}
              >
                <div
                  className="h-4 rounded-r-[4px]"
                  style={{
                    width: `${Math.max(pct, 3)}%`,
                    background: SERIES[i % SERIES.length],
                    marginLeft: "1px",
                  }}
                />
              </div>
              <span
                className="w-6 shrink-0 text-xs font-medium"
                style={{ color: "var(--chart-ink-secondary)" }}
              >
                {d.count}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
