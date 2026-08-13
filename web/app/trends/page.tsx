"use client";

import { useEffect, useState } from "react";
import { fetchTrends, fetchDigest } from "@/lib/queries";
import type { DayPoint, SavingsDigest } from "@/lib/types";
import LineChart from "@/components/LineChart";
import StatTile from "@/components/StatTile";
import PageHeader from "@/components/PageHeader";

const RANGES = [7, 30, 90];

export default function TrendsPage() {
  const [days, setDays] = useState(30);
  const [trends, setTrends] = useState<DayPoint[]>([]);
  const [digest, setDigest] = useState<SavingsDigest | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchTrends(days), fetchDigest()])
      .then(([t, d]) => {
        if (cancelled) return;
        setTrends(t);
        setDigest(d);
        setError(false);
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [days]);

  const mttrPoints = trends
    .filter((d) => d.mttrMinutes != null)
    .map((d) => ({ label: d.day, value: d.mttrMinutes as number }));

  return (
    <div className="px-4 py-5 space-y-5 sm:px-6 md:px-8 md:py-7 md:space-y-7">
      <PageHeader
        title="Trends"
        subtitle="How the loop performs over time — incident volume, exposure, and time to close."
        live={!error}
        actions={
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDays(r)}
                className={`rounded-md border px-3 py-1.5 text-xs transition ${
                  days === r
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border text-muted hover:bg-surface-hover hover:text-foreground"
                }`}
              >
                {r}d
              </button>
            ))}
          </div>
        }
      />

      {error && (
        <div className="card border-bad/40 bg-bad-soft p-4 text-sm text-bad">
          Can&apos;t reach the backend.
        </div>
      )}

      {digest && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 md:grid-cols-4">
          <StatTile label="Incidents handled" value={digest.incidents} />
          <StatTile label="Actions applied" value={digest.actionsApplied} tone="good" />
          <StatTile label="Engineer-hours saved" value={digest.hoursSaved} suffix=" h" tone="good" />
          <StatTile
            label="Actions failed"
            value={digest.actionsFailed}
            tone={digest.actionsFailed > 0 ? "bad" : "good"}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="text-sm font-medium">Incidents per day</h2>
          <p className="mb-3 text-xs text-muted">Detected, all outcomes</p>
          <LineChart
            data={trends.map((d) => ({ label: d.day, value: d.total }))}
            color="var(--series-1)"
            format={(v) => String(Math.round(v))}
            integer
          />
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-medium">Exposure per day</h2>
          <p className="mb-3 text-xs text-muted">Estimated dollars at risk</p>
          <LineChart
            data={trends.map((d) => ({ label: d.day, value: d.exposureUsd }))}
            color="var(--series-2)"
            format={(v) => (v >= 1000 ? `$${(v / 1000).toFixed(0)}K` : `$${Math.round(v)}`)}
          />
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-medium">Mean time to close</h2>
          <p className="mb-3 text-xs text-muted">
            Minutes from detection to resolution — the number that should trend down
            as memory grows
          </p>
          <LineChart
            data={mttrPoints}
            color="var(--series-3)"
            format={(v) => `${Math.round(v)}m`}
            emptyMessage="No closed incidents yet"
          />
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-medium">Actions taken</h2>
          <p className="mb-3 text-xs text-muted">Across every incident on record</p>
          {digest && digest.byAction.length > 0 ? (
            <ul className="mt-4 space-y-2">
              {digest.byAction.map((a) => {
                const max = Math.max(...digest.byAction.map((x) => x.count));
                return (
                  <li key={a.actionType} className="flex items-center gap-3">
                    <span className="w-36 shrink-0 text-right text-xs text-muted">
                      {a.actionType.replace(/_/g, " ")}
                    </span>
                    <div className="h-4 flex-1 rounded-sm" style={{ background: "var(--chart-gridline)" }}>
                      <div
                        className="h-4 rounded-r-[4px]"
                        style={{
                          width: `${Math.max((a.count / max) * 100, 3)}%`,
                          background: "var(--series-4)",
                        }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-xs tabular-nums">{a.count}</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="py-8 text-center text-sm text-muted">No actions recorded yet</p>
          )}
        </section>
      </div>
    </div>
  );
}
