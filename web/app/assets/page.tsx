"use client";

import { useEffect, useState } from "react";
import { fetchTrustBadges } from "@/lib/queries";
import type { TrustBadge } from "@/lib/types";
import { fetchActionsConfig, runRescore, fetchJob, type Job } from "@/lib/actions";

const GRADE_TONE: Record<string, string> = {
  A: "text-good bg-good-soft",
  B: "text-info bg-info-soft",
  C: "text-warn bg-warn-soft",
  D: "text-bad bg-bad-soft",
};

export default function AssetsPage() {
  const [badges, setBadges] = useState<TrustBadge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [canRescore, setCanRescore] = useState(false);
  const [job, setJob] = useState<Job | null>(null);

  const load = () =>
    fetchTrustBadges()
      .then((b) => {
        setBadges(b);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
    fetchActionsConfig()
      .then((c) => setCanRescore(c.allowRescore))
      .catch(() => setCanRescore(false));
  }, []);

  // Poll the running job until it settles, then refresh the scores it rewrote.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const id = setInterval(async () => {
      const updated = await fetchJob(job.id);
      if (updated) {
        setJob(updated);
        if (updated.status !== "running") load();
      }
    }, 1500);
    return () => clearInterval(id);
  }, [job]);

  async function rescore() {
    try {
      setJob(await runRescore());
    } catch (e) {
      setJob({
        id: "-", kind: "rescore", target: "-", status: "failed",
        log: [], error: String(e), started_at: new Date().toISOString(),
        finished_at: null,
      });
    }
  }

  return (
    <div className="px-8 py-7 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Asset health</h1>
          <p className="mt-1 text-sm text-muted">
            Live trust score per asset, worst first. Computed from failing
            assertions, open incidents, volume and freshness drift, and incident
            history.
          </p>
        </div>
        {canRescore && (
          <button
            onClick={rescore}
            disabled={job?.status === "running"}
            className="rounded-lg border border-border px-3 py-2 text-xs hover:bg-surface-raised disabled:opacity-40"
          >
            {job?.status === "running" ? "Rescoring…" : "Recompute & publish"}
          </button>
        )}
      </div>

      {job && (
        <div
          className={`card p-4 text-xs ${
            job.status === "failed" ? "border-bad/40 bg-bad-soft text-bad" : ""
          }`}
        >
          <p className="font-medium">
            Rescore {job.status}
            {job.error ? `: ${job.error}` : ""}
          </p>
          {job.log.length > 0 && (
            <ul className="mt-2 space-y-0.5 font-mono text-muted">
              {job.log.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && (
        <div className="card border-bad/40 bg-bad-soft p-4 text-sm text-bad">
          Can&apos;t load trust scores — is DataHub reachable?
        </div>
      )}

      {loading ? (
        <p className="py-12 text-center text-sm text-muted">Scoring assets…</p>
      ) : badges.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted">
          No dbt datasets found in DataHub.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {badges.map((b) => (
            <div key={b.assetUrn} className="card p-5">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="truncate font-medium">{b.assetName}</p>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-muted">
                    {b.assetUrn}
                  </p>
                </div>
                <span
                  className={`ml-3 shrink-0 rounded-lg px-2.5 py-1 text-sm font-semibold ${
                    GRADE_TONE[b.grade] ?? "text-muted bg-surface-raised"
                  }`}
                >
                  {b.grade}
                </span>
              </div>

              <div className="mt-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-semibold">{b.score}</span>
                  <span className="text-xs text-muted">/ 100</span>
                </div>
                <div
                  className="mt-2 h-1.5 rounded-full"
                  style={{ background: "var(--chart-gridline)" }}
                >
                  <div
                    className="h-1.5 rounded-full"
                    style={{
                      width: `${b.score}%`,
                      background:
                        b.score >= 90
                          ? "var(--status-good)"
                          : b.score >= 70
                            ? "var(--status-warn)"
                            : "var(--status-bad)",
                    }}
                  />
                </div>
              </div>

              <ul className="mt-4 space-y-1 text-xs text-muted">
                <Signal label="Failing assertions" value={b.failedAssertions} bad={b.failedAssertions > 0} />
                <Signal label="Open incident" value={b.openIncident ? "yes" : "no"} bad={b.openIncident} />
                <Signal label="Past incidents" value={b.pastIncidents} bad={b.pastIncidents > 2} />
                {Math.abs(b.volumeShift) >= 0.01 && (
                  <Signal
                    label="Volume shift"
                    value={`${(b.volumeShift * 100).toFixed(0)}%`}
                    bad={Math.abs(b.volumeShift) >= 0.25}
                  />
                )}
                {b.freshnessLagHours > 0 && (
                  <Signal
                    label="Freshness lag"
                    value={`${b.freshnessLagHours.toFixed(0)}h`}
                    bad={b.freshnessLagHours > 24}
                  />
                )}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Signal({
  label, value, bad,
}: { label: string; value: string | number; bad?: boolean }) {
  return (
    <li className="flex items-center justify-between">
      <span>{label}</span>
      <span className={bad ? "text-bad" : "text-foreground"}>{value}</span>
    </li>
  );
}
