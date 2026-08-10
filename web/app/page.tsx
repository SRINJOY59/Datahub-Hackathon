"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchStats, fetchIncidents, fetchTrends, fetchDigest } from "@/lib/queries";
import type { Stats, Incident, DayPoint, SavingsDigest } from "@/lib/types";
import StatTile from "@/components/StatTile";
import BreakdownChart from "@/components/BreakdownChart";
import PageHeader from "@/components/PageHeader";
import { SkeletonTile, SkeletonRows } from "@/components/Skeleton";
import { StatusBadge, TierBadge } from "@/components/Badge";

const POLL_MS = 12_000;

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.round(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

export default function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<Incident[]>([]);
  const [trends, setTrends] = useState<DayPoint[]>([]);
  const [digest, setDigest] = useState<SavingsDigest | null>(null);
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([fetchStats(), fetchIncidents({ limit: 7 }), fetchTrends(14), fetchDigest()])
        .then(([s, inc, t, d]) => {
          if (cancelled) return;
          setStats(s);
          setRecent(inc);
          setTrends(t);
          setDigest(d);
          setError(false);
          setLoaded(true);
        })
        .catch(() => {
          if (!cancelled) {
            setError(true);
            setLoaded(true);
          }
        });
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const sparkTotals = trends.map((d) => d.total);
  const sparkCost = trends.map((d) => d.exposureUsd);

  return (
    <div className="px-8 py-7 space-y-7">
      <PageHeader
        title="Overview"
        subtitle="Live state of the remediation loop — detect, diagnose, act, validate."
        live={!error}
        actions={
          <kbd className="hidden rounded-md border border-border bg-surface px-2 py-1 text-[11px] text-muted-dim md:inline-block">
            ⌘K
          </kbd>
        }
      />

      {error && (
        <div className="card border-bad/40 p-4 text-sm text-bad">
          Can&apos;t reach the backend. Is <code>python -m agent serve</code> running
          on port 8000?
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {!loaded ? (
          <>
            <SkeletonTile /><SkeletonTile /><SkeletonTile /><SkeletonTile />
          </>
        ) : (
          <>
            <StatTile
              label="Open incidents"
              value={stats?.open ?? 0}
              tone={stats && stats.open > 0 ? "warn" : "good"}
              hint={stats && stats.open === 0 ? "pipeline is clean" : "needs attention"}
            />
            <StatTile
              label="Resolved"
              value={stats?.resolved ?? 0}
              tone="good"
              spark={sparkTotals}
              hint={`${stats?.total ?? 0} total on record`}
            />
            <StatTile
              label="Mean time to close"
              value={stats?.mttrMinutes ?? 0}
              suffix=" min"
              hint="detection → resolution"
            />
            <StatTile
              label="Exposure avoided"
              value={stats?.exposureUsd ?? 0}
              prefix="$"
              spark={sparkCost}
              hint={digest ? `${digest.hoursSaved.toFixed(0)}h engineer time saved` : undefined}
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-5">
        <section className="card card-accent p-6 xl:col-span-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-medium">Incidents by change type</h2>
            <Link href="/trends" className="text-xs text-accent hover:underline">
              trends →
            </Link>
          </div>
          <p className="mt-1 text-xs text-muted-dim">
            What actually breaks, across every incident on record
          </p>
          <div className="mt-5">
            <BreakdownChart data={stats?.byChangeType ?? []} />
          </div>
        </section>

        <section className="card p-6 xl:col-span-2">
          <h2 className="text-sm font-medium">Autonomy split</h2>
          <p className="mt-1 text-xs text-muted-dim">
            How much the agent handled without a human
          </p>
          {digest ? (
            <div className="mt-5 space-y-4">
              <Meter
                label="Applied automatically"
                value={digest.actionsApplied}
                total={digest.actionsApplied + digest.actionsFailed}
                color="var(--status-good)"
              />
              {digest.actionsFailed > 0 && (
                <Meter
                  label="Failed / rolled back"
                  value={digest.actionsFailed}
                  total={digest.actionsApplied + digest.actionsFailed}
                  color="var(--status-bad)"
                />
              )}
              <div className="grid grid-cols-2 gap-3 border-t border-border pt-4">
                <MiniFact label="Incidents" value={String(digest.incidents)} />
                <MiniFact label="Hours saved" value={`${digest.hoursSaved.toFixed(1)}h`} />
              </div>
              {digest.shadowMode && (
                <p className="rounded-md bg-warn-soft px-2.5 py-1.5 text-[11px] text-warn">
                  Shadow mode — these actions were planned, not applied.
                </p>
              )}
            </div>
          ) : (
            <div className="mt-5"><SkeletonRows rows={3} /></div>
          )}
        </section>
      </div>

      <section className="card p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium">Recent incidents</h2>
            <p className="mt-1 text-xs text-muted-dim">Newest first</p>
          </div>
          <Link href="/incidents" className="text-xs text-accent hover:underline">
            View all →
          </Link>
        </div>

        <div className="mt-5">
          {!loaded ? (
            <SkeletonRows rows={4} />
          ) : recent.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-sm text-muted">No incidents recorded yet.</p>
              <p className="mt-1 text-xs text-muted-dim">
                Run a fire drill from the Activity page to see the loop work.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {recent.map((inc, i) => (
                <Link
                  key={inc.id}
                  href={`/incidents/${inc.id}`}
                  className="fade-up group flex items-center gap-4 rounded-lg border border-transparent px-3 py-3 transition hover:border-border hover:bg-surface-hover"
                  style={{ animationDelay: `${i * 30}ms` }}
                >
                  <span
                    className={`h-8 w-[3px] shrink-0 rounded-full ${
                      inc.status === "resolved"
                        ? "bg-good"
                        : inc.status === "contained"
                          ? "bg-warn"
                          : inc.status === "open"
                            ? "bg-info"
                            : "bg-bad"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-muted-dim">{inc.id}</span>
                      <span className="truncate text-sm font-medium">
                        {inc.assetName ?? inc.assetUrn}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted">
                      {inc.changeType?.replace(/_/g, " ") ?? "unknown"} ·{" "}
                      {timeAgo(inc.detectedAt)}
                      {inc.minutesToClose != null &&
                        ` · closed in ${Math.round(inc.minutesToClose)}m`}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <TierBadge tier={inc.tier} />
                    <StatusBadge status={inc.status} />
                    <span className="w-16 text-right text-xs tabular-nums text-muted">
                      {inc.costUsd != null
                        ? `$${Math.round(inc.costUsd).toLocaleString()}`
                        : "—"}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function Meter({
  label, value, total, color,
}: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums">{value}</span>
      </div>
      <div
        className="mt-1.5 h-1.5 overflow-hidden rounded-full"
        style={{ background: "var(--chart-gridline)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}

function MiniFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-dim">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
