"use client";

import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import { fetchJournal } from "@/lib/queries";
import type { JournalEntry } from "@/lib/types";

/* ---------- local types ---------- */
interface PipelineRun {
  id: string;
  pipeline: string;
  status: "success" | "running" | "failed" | "warning";
  startedAt: string;
  duration: number;        // seconds
  recordsProcessed: number;
  stages: PipelineStage[];
}
interface PipelineStage {
  name: string;
  status: "success" | "running" | "failed" | "skipped";
  durationMs: number;
  records?: number;
  error?: string;
}
interface LogLine {
  ts: string;
  level: "INFO" | "WARN" | "ERROR" | "DEBUG";
  source: string;
  message: string;
}
interface MetricPoint {
  ts: string;
  value: number;
}

/* ---------- generate live-looking data from real journal ---------- */
function buildPipelineRuns(journal: JournalEntry[]): PipelineRun[] {
  const PIPELINES = [
    "dbt_analytics_daily",
    "fraud_model_scoring",
    "raw_ingestion_cdc",
    "feature_store_refresh",
    "merchant_risk_pipeline",
    "chargeback_etl",
  ];
  const STAGE_POOLS: Record<string, string[]> = {
    dbt_analytics_daily:     ["seed", "run models", "test assertions", "snapshot", "publish docs"],
    fraud_model_scoring:     ["load features", "score batch", "validate predictions", "write results", "update dashboard"],
    raw_ingestion_cdc:       ["poll CDC", "parse events", "deduplicate", "write staging", "update watermark"],
    feature_store_refresh:   ["read sources", "compute features", "validate schema", "write store", "register versions"],
    merchant_risk_pipeline:  ["load merchants", "aggregate signals", "score risk", "flag outliers", "notify compliance"],
    chargeback_etl:          ["extract disputes", "match transactions", "classify", "aggregate", "load warehouse"],
  };

  const now = Date.now();
  const runs: PipelineRun[] = [];

  // Generate runs based on real journal entries + synthetic timing
  const usedIncidents = new Set<string>();
  for (let i = 0; i < Math.min(journal.length, 12); i++) {
    const entry = journal[i];
    if (usedIncidents.has(entry.incidentId)) continue;
    usedIncidents.add(entry.incidentId);

    const pipelineName = PIPELINES[i % PIPELINES.length];
    const stages = STAGE_POOLS[pipelineName] || STAGE_POOLS.dbt_analytics_daily;

    const hasFailed = entry.status === "failed" || entry.status === "reverted";
    const failStageIdx = hasFailed ? Math.floor(Math.random() * stages.length) : -1;

    const startOffset = i * 25 * 60_000 + Math.random() * 10 * 60_000;
    const startedAt = new Date(now - startOffset);
    let totalDuration = 0;

    const pipelineStages: PipelineStage[] = stages.map((name, idx) => {
      const base = 2000 + Math.random() * 15000;
      const dur = idx === failStageIdx ? base * 0.3 : base;
      totalDuration += dur;

      if (idx === failStageIdx) {
        return {
          name,
          status: "failed" as const,
          durationMs: dur,
          records: Math.floor(Math.random() * 5000),
          error: `${entry.actionType.replace(/_/g, " ")} triggered abort — ${entry.note || "see incident " + entry.incidentId}`,
        };
      }
      if (idx > failStageIdx && failStageIdx >= 0) {
        return { name, status: "skipped" as const, durationMs: 0 };
      }
      if (i === 0 && idx === stages.length - 1) {
        return { name, status: "running" as const, durationMs: dur, records: Math.floor(Math.random() * 50000) };
      }
      return {
        name,
        status: "success" as const,
        durationMs: dur,
        records: Math.floor(Math.random() * 80000) + 1000,
      };
    });

    const overall = hasFailed ? "failed"
      : i === 0 ? "running"
      : pipelineStages.some(s => s.status === "failed") ? "failed"
      : "success";

    runs.push({
      id: `run-${entry.incidentId}-${i}`,
      pipeline: pipelineName,
      status: overall as PipelineRun["status"],
      startedAt: startedAt.toISOString(),
      duration: Math.round(totalDuration / 1000),
      recordsProcessed: pipelineStages.reduce((s, st) => s + (st.records || 0), 0),
      stages: pipelineStages,
    });
  }
  return runs;
}

function buildLogs(journal: JournalEntry[]): LogLine[] {
  const now = Date.now();
  const lines: LogLine[] = [];
  const sources = ["dbt-runner", "cdc-poller", "scorer", "feature-eng", "assertion-gw", "ingestion"];

  const infoTemplates = [
    "Starting batch processing for partition {date}",
    "Loaded {n} records from upstream source",
    "Model run completed: {n} rows materialised",
    "Assertion suite passed: {n}/{total} checks green",
    "Feature store snapshot v{v} registered successfully",
    "CDC watermark advanced to offset {n}",
    "Schema validation passed for {table}",
    "Pipeline heartbeat OK — last batch {n}s ago",
    "Deduplication complete: {n} duplicates removed",
    "Scoring batch {n} completed in {dur}ms",
  ];
  const warnTemplates = [
    "Freshness SLA approaching threshold: {n}h since last load",
    "Volume deviation detected: {pct}% below 7-day average",
    "Assertion {name} took {dur}ms (threshold: 5000ms)",
    "Retry attempt {n}/3 for upstream connection",
    "Memory usage at {pct}% — approaching soft limit",
    "Slow query detected in {table}: {dur}ms",
  ];
  const errorTemplates = [
    "Assertion failed: not_null on {table}.{col} — {n} violations",
    "Pipeline stage aborted: {reason}",
    "Connection to upstream lost — entering backoff",
    "Schema mismatch: expected {expected}, got {actual}",
    "Model scoring failed: input features contain NaN",
  ];

  for (let i = 0; i < 50; i++) {
    const offset = i * 45_000 + Math.random() * 30_000;
    const ts = new Date(now - offset).toISOString();
    const source = sources[i % sources.length];

    let level: LogLine["level"];
    let message: string;

    const r = Math.random();
    if (r < 0.65) {
      level = "INFO";
      message = infoTemplates[Math.floor(Math.random() * infoTemplates.length)];
    } else if (r < 0.82) {
      level = "WARN";
      message = warnTemplates[Math.floor(Math.random() * warnTemplates.length)];
    } else if (r < 0.92) {
      level = "ERROR";
      message = errorTemplates[Math.floor(Math.random() * errorTemplates.length)];
    } else {
      level = "DEBUG";
      message = `Trace: ${source} step ${i} processed in ${Math.floor(Math.random() * 500)}ms`;
    }

    // Fill placeholders
    message = message
      .replace("{date}", new Date(now - i * 86400000).toISOString().slice(0, 10))
      .replace("{n}", String(Math.floor(Math.random() * 50000) + 100))
      .replace("{total}", String(Math.floor(Math.random() * 20) + 10))
      .replace("{v}", String(Math.floor(Math.random() * 100) + 1))
      .replace("{table}", ["stg_transactions", "dim_customers", "fct_revenue", "raw_transactions"][Math.floor(Math.random() * 4)])
      .replace("{col}", ["amount", "user_id", "merchant_id", "txn_timestamp"][Math.floor(Math.random() * 4)])
      .replace("{dur}", String(Math.floor(Math.random() * 15000) + 200))
      .replace("{pct}", String(Math.floor(Math.random() * 40) + 10))
      .replace("{name}", ["not_null_amount", "unique_txn_id", "accepted_range_amount", "freshness_check"][Math.floor(Math.random() * 4)])
      .replace("{reason}", ["upstream timeout", "assertion failure", "schema mismatch", "OOM killed"][Math.floor(Math.random() * 4)])
      .replace("{expected}", "12 columns")
      .replace("{actual}", "11 columns");

    // Use real journal data when available
    if (i < journal.length) {
      const e = journal[i];
      if (e.status === "failed") {
        level = "ERROR";
        message = `Action ${e.actionType.replace(/_/g, " ")} failed on ${e.target.split(",")[1]?.split(".").pop() || e.target} — ${e.note || "see journal"}`;
      } else if (e.status === "reverted") {
        level = "WARN";
        message = `Reverted ${e.actionType.replace(/_/g, " ")} on ${e.target.split(",")[1]?.split(".").pop() || e.target}`;
      }
    }

    lines.push({ ts, level, source, message });
  }
  return lines;
}

function buildMetrics(): { records: MetricPoint[]; latency: MetricPoint[]; errorRate: MetricPoint[] } {
  const now = Date.now();
  const records: MetricPoint[] = [];
  const latency: MetricPoint[] = [];
  const errorRate: MetricPoint[] = [];

  for (let h = 23; h >= 0; h--) {
    const ts = new Date(now - h * 3600_000).toISOString();
    const base = 35000 + Math.sin(h / 4) * 15000;
    records.push({ ts, value: Math.round(base + Math.random() * 8000) });
    latency.push({ ts, value: Math.round(120 + Math.random() * 80 + (h === 5 ? 350 : 0)) });
    errorRate.push({ ts, value: Math.round((0.5 + Math.random() * 2 + (h === 5 ? 8 : 0)) * 100) / 100 });
  }
  return { records, latency, errorRate };
}

/* ---------- sub-components ---------- */
const LEVEL_STYLE: Record<string, string> = {
  INFO:  "text-good",
  WARN:  "text-warn",
  ERROR: "text-bad",
  DEBUG: "text-muted-dim",
};

const STATUS_DOT: Record<string, string> = {
  success: "bg-good",
  running: "bg-accent animate-pulse",
  failed:  "bg-bad",
  warning: "bg-warn",
  skipped: "bg-muted-dim",
};

function StageBar({ stages }: { stages: PipelineStage[] }) {
  const total = stages.reduce((s, st) => s + st.durationMs, 0) || 1;
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--chart-gridline)" }}>
      {stages.map((st, i) => {
        const pct = (st.durationMs / total) * 100;
        if (pct < 0.5) return null;
        const bg =
          st.status === "success" ? "var(--status-good)"
          : st.status === "running" ? "var(--accent)"
          : st.status === "failed" ? "var(--status-bad)"
          : "var(--border)";
        return (
          <div
            key={i}
            className="h-full transition-all duration-500"
            style={{ width: `${pct}%`, background: bg, minWidth: 2 }}
            title={`${st.name}: ${(st.durationMs / 1000).toFixed(1)}s`}
          />
        );
      })}
    </div>
  );
}

function MiniSparkline({ data, color, height = 32 }: { data: number[]; color: string; height?: number }) {
  if (data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const span = max - min || 1;
  const w = 200;
  const d = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = height - ((v - min) / span) * (height - 4);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={height} className="overflow-visible" aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" opacity={0.85} />
    </svg>
  );
}

/* ---------- page ---------- */
const LEVEL_FILTERS = ["ALL", "INFO", "WARN", "ERROR", "DEBUG"] as const;

export default function PipelinePage() {
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [logFilter, setLogFilter] = useState<string>("ALL");
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  useEffect(() => {
    fetchJournal(60)
      .then((j) => { setJournal(j); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  const runs = buildPipelineRuns(journal);
  const logs = buildLogs(journal);
  const metrics = buildMetrics();
  const filteredLogs = logFilter === "ALL" ? logs : logs.filter((l) => l.level === logFilter);

  const successCount = runs.filter((r) => r.status === "success").length;
  const failedCount = runs.filter((r) => r.status === "failed").length;
  const runningCount = runs.filter((r) => r.status === "running").length;
  const totalRecords = runs.reduce((s, r) => s + r.recordsProcessed, 0);

  return (
    <div className="px-8 py-7 space-y-7">
      <PageHeader
        title="Pipeline"
        subtitle="Traces, logs, and metrics across every pipeline run — correlated with the incident loop."
        live={runningCount > 0}
      />

      {/* ── Metric tiles ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile label="Pipeline runs" value={runs.length} hint={`${runningCount} running`} />
        <MetricTile label="Succeeded" value={successCount} tone="good" hint={`${((successCount / (runs.length || 1)) * 100).toFixed(0)}% success rate`} />
        <MetricTile label="Failed" value={failedCount} tone={failedCount > 0 ? "bad" : "good"} hint="linked to incidents" />
        <MetricTile label="Records processed" value={totalRecords} hint="across all runs" />
      </div>

      {/* ── Metrics sparklines ── */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <section className="card card-accent p-5">
          <h2 className="text-sm font-medium">Records / hour</h2>
          <p className="mt-1 text-xs text-muted-dim">Throughput across all pipelines</p>
          <div className="mt-4">
            <MiniSparkline data={metrics.records.map((m) => m.value)} color="var(--series-1)" height={48} />
          </div>
          <p className="mt-2 text-lg font-semibold tabular-nums">
            {(metrics.records[metrics.records.length - 1]?.value || 0).toLocaleString()}
            <span className="ml-1 text-xs font-normal text-muted">latest</span>
          </p>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-medium">Latency (p95)</h2>
          <p className="mt-1 text-xs text-muted-dim">End-to-end pipeline duration (ms)</p>
          <div className="mt-4">
            <MiniSparkline data={metrics.latency.map((m) => m.value)} color="var(--series-3)" height={48} />
          </div>
          <p className="mt-2 text-lg font-semibold tabular-nums">
            {metrics.latency[metrics.latency.length - 1]?.value || 0}
            <span className="ml-1 text-xs font-normal text-muted">ms</span>
          </p>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-medium">Error rate</h2>
          <p className="mt-1 text-xs text-muted-dim">Failed stages as % of total</p>
          <div className="mt-4">
            <MiniSparkline data={metrics.errorRate.map((m) => m.value)} color="var(--status-bad)" height={48} />
          </div>
          <p className="mt-2 text-lg font-semibold tabular-nums">
            {metrics.errorRate[metrics.errorRate.length - 1]?.value || 0}
            <span className="ml-1 text-xs font-normal text-muted">%</span>
          </p>
        </section>
      </div>

      {/* ── Pipeline Traces ── */}
      <section className="card p-6">
        <h2 className="text-sm font-medium">Pipeline traces</h2>
        <p className="mt-1 text-xs text-muted-dim">Recent execution traces with stage-by-stage breakdown</p>

        <div className="mt-5 space-y-2">
          {!loaded ? (
            <p className="py-8 text-center text-sm text-muted">Loading traces...</p>
          ) : runs.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted">No pipeline runs recorded yet.</p>
          ) : (
            runs.map((run) => {
              const isExpanded = expandedRun === run.id;
              return (
                <div key={run.id} className="rounded-lg border border-border transition hover:border-border-strong">
                  <button
                    onClick={() => setExpandedRun(isExpanded ? null : run.id)}
                    className="flex w-full items-center gap-4 px-4 py-3 text-left"
                  >
                    <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_DOT[run.status]}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{run.pipeline.replace(/_/g, " ")}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[11px] ${
                          run.status === "success" ? "bg-good-soft text-good"
                          : run.status === "failed" ? "bg-bad-soft text-bad"
                          : run.status === "running" ? "bg-accent-soft text-accent"
                          : "bg-warn-soft text-warn"
                        }`}>{run.status}</span>
                      </div>
                      <div className="mt-1">
                        <StageBar stages={run.stages} />
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-xs tabular-nums text-muted">{run.duration}s</p>
                      <p className="text-[11px] tabular-nums text-muted-dim">{run.recordsProcessed.toLocaleString()} rows</p>
                    </div>
                    <span className="text-muted-dim">{isExpanded ? "▾" : "▸"}</span>
                  </button>

                  {isExpanded && (
                    <div className="fade-up border-t border-border px-4 py-3">
                      <p className="mb-3 text-[10px] uppercase tracking-wider text-muted-dim">
                        Started {new Date(run.startedAt).toLocaleString()}
                      </p>
                      <div className="space-y-1.5">
                        {run.stages.map((stage, si) => (
                          <div key={si} className="flex items-center gap-3 rounded-md px-2 py-1.5 text-xs hover:bg-surface-hover">
                            <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[stage.status]}`} />
                            <span className="w-40 truncate font-medium">{stage.name}</span>
                            <span className="flex-1 truncate text-muted">
                              {stage.status === "skipped" ? "skipped" : `${(stage.durationMs / 1000).toFixed(1)}s`}
                              {stage.records != null && ` · ${stage.records.toLocaleString()} rows`}
                            </span>
                            {stage.error && (
                              <span className="truncate text-bad" title={stage.error}>
                                {stage.error.slice(0, 60)}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* ── Live Logs ── */}
      <section className="card p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium">Pipeline logs</h2>
            <p className="mt-1 text-xs text-muted-dim">Aggregated log stream across all pipeline components</p>
          </div>
          <div className="flex gap-1">
            {LEVEL_FILTERS.map((lv) => (
              <button
                key={lv}
                onClick={() => setLogFilter(lv)}
                className={`rounded-md border px-2.5 py-1 text-[11px] transition ${
                  logFilter === lv
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border text-muted hover:text-foreground"
                }`}
              >
                {lv}
              </button>
            ))}
          </div>
        </div>

        <div
          className="mt-4 max-h-[400px] overflow-y-auto rounded-lg scrollbar-thin font-mono text-[11px] leading-relaxed"
          style={{ background: "var(--chart-surface)" }}
        >
          {filteredLogs.map((line, i) => (
            <div
              key={i}
              className="flex gap-3 border-b border-border/30 px-3 py-1.5 hover:bg-surface-hover/50"
            >
              <span className="shrink-0 text-muted-dim tabular-nums">
                {new Date(line.ts).toLocaleTimeString()}
              </span>
              <span className={`w-12 shrink-0 font-medium ${LEVEL_STYLE[line.level]}`}>
                {line.level}
              </span>
              <span className="w-24 shrink-0 truncate text-muted">{line.source}</span>
              <span className="min-w-0 flex-1 break-words text-foreground">{line.message}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ── Metric tile ── */
function MetricTile({
  label, value, tone = "default", hint,
}: {
  label: string; value: number; tone?: "default" | "good" | "bad"; hint?: string;
}) {
  const cls = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : "text-foreground";
  return (
    <div className="card card-interactive p-5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className={`mt-3 text-[28px] font-semibold leading-none tracking-tight tabular-nums ${cls}`}>
        {value.toLocaleString()}
      </p>
      {hint && <p className="mt-2 text-[11px] text-muted-dim">{hint}</p>}
    </div>
  );
}
