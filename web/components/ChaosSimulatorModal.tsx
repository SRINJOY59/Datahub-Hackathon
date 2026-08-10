"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { API_URL } from "@/lib/graphql";
import { fetchChaosScenarios } from "@/lib/queries";
import type { ChaosDrillResult, ChaosScenarioInfo } from "@/lib/types";

interface ChaosSimulatorModalProps {
  open: boolean;
  onClose: () => void;
  onDrillComplete?: (result: ChaosDrillResult) => void;
}

interface LogEntry {
  id: string;
  stage: string;
  message: string;
  timestamp: string;
}

const STAGES = [
  { id: "system", label: "Reset & Init", icon: "🔄" },
  { id: "inject", label: "Inject Fault", icon: "⚡" },
  { id: "detect", label: "Detect Signal", icon: "📡" },
  { id: "context", label: "Graph Lineage", icon: "🕸️" },
  { id: "rca", label: "LLM Causality", icon: "🧠" },
  { id: "policy", label: "Policy & Gate", icon: "🛡️" },
  { id: "act", label: "Actuate Fix", icon: "🛠️" },
  { id: "validate", label: "Validate Gate", icon: "✅" },
  { id: "resolve", label: "Graph Writeback", icon: "📊" },
];

const CATEGORY_MAP: Record<string, { label: string; color: string; icon: string }> = {
  data: { label: "Data Quality", color: "border-warn/30 bg-warn-soft/20 text-warn", icon: "🗄️" },
  drift: { label: "Distribution Drift", color: "border-info/30 bg-info-soft/20 text-info", icon: "📉" },
  model: { label: "ML & Skew", color: "border-purple-500/30 bg-purple-500/10 text-purple-400", icon: "🤖" },
  code: { label: "Supply Chain & Code", color: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400", icon: "📦" },
  freshness: { label: "Pipeline Health", color: "border-amber-500/30 bg-amber-500/10 text-amber-400", icon: "⏱️" },
};

function getCategoryInfo(cat?: string) {
  if (!cat) return { label: "General", color: "border-muted/30 bg-surface-raised text-muted", icon: "⚡" };
  const lower = cat.toLowerCase();
  for (const [key, val] of Object.entries(CATEGORY_MAP)) {
    if (lower.includes(key)) return val;
  }
  return { label: cat, color: "border-accent/30 bg-accent-soft text-accent", icon: "⚡" };
}

function getStageBadgeColor(stage: string) {
  switch (stage.toLowerCase()) {
    case "detect":
      return "text-cyan-400 border-cyan-500/30 bg-cyan-950/40";
    case "context":
      return "text-blue-400 border-blue-500/30 bg-blue-950/40";
    case "rca":
      return "text-purple-400 border-purple-500/30 bg-purple-950/40";
    case "policy":
      return "text-amber-400 border-amber-500/30 bg-amber-950/40";
    case "plan":
      return "text-indigo-400 border-indigo-500/30 bg-indigo-950/40";
    case "act":
    case "restore":
      return "text-emerald-400 border-emerald-500/30 bg-emerald-950/40";
    case "validate":
      return "text-teal-400 border-teal-500/30 bg-teal-950/40";
    case "rollback":
    case "contain":
      return "text-rose-400 border-rose-500/30 bg-rose-950/40";
    case "cost":
      return "text-green-400 border-green-500/30 bg-green-950/40";
    case "escalate":
      return "text-red-400 border-red-500/30 bg-red-950/40";
    default:
      return "text-muted border-border bg-surface-raised";
  }
}

export default function ChaosSimulatorModal({ open, onClose, onDrillComplete }: ChaosSimulatorModalProps) {
  const [scenarios, setScenarios] = useState<ChaosScenarioInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string>("schema_change");
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [searchFilter, setSearchFilter] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [injecting, setInjecting] = useState(false);
  const [activeStageId, setActiveStageId] = useState<string>("system");
  const [completedStages, setCompletedStages] = useState<Set<string>>(new Set());
  const [parsedLogs, setParsedLogs] = useState<LogEntry[]>([]);
  const [result, setResult] = useState<ChaosDrillResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copiedLogs, setCopiedLogs] = useState<boolean>(false);

  const terminalEndRef = useRef<HTMLDivElement | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!open) return;
    let active = true;

    setLoading(true);
    fetchChaosScenarios()
      .then((s) => {
        if (!active) return;
        setScenarios(s);
        if (s.length > 0 && !selectedId) {
          setSelectedId(s[0].id);
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [open]);

  // Scroll terminal to bottom as logs stream in
  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [parsedLogs, autoScroll]);

  // Timer while injecting
  useEffect(() => {
    if (injecting) {
      setElapsedSeconds(0);
      timerRef.current = setInterval(() => {
        setElapsedSeconds((prev) => +(prev + 0.1).toFixed(1));
      }, 100);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [injecting]);

  if (!open) return null;

  const activeScenario = scenarios.find((s) => s.id === selectedId) || scenarios[0];

  const categories = Array.from(new Set(scenarios.map((s) => s.category || "General")));

  const filteredScenarios = scenarios.filter((s) => {
    const matchCat = activeCategory === "all" || s.category === activeCategory;
    const matchSearch =
      !searchFilter ||
      s.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
      s.description.toLowerCase().includes(searchFilter.toLowerCase()) ||
      s.id.toLowerCase().includes(searchFilter.toLowerCase());
    return matchCat && matchSearch;
  });

  const handleCopyLogs = () => {
    const text = parsedLogs.map((l) => `[${l.timestamp}] [${l.stage}] ${l.message}`).join("\n");
    navigator.clipboard.writeText(text);
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 2000);
  };

  const handleResetToSetup = () => {
    setInjecting(false);
    setResult(null);
    setError(null);
    setParsedLogs([]);
    setCompletedStages(new Set());
    setActiveStageId("system");
  };

  const mapStageToTimeline = (stage: string) => {
    const s = stage.toLowerCase();
    if (s.includes("system") || s.includes("reset")) return "system";
    if (s.includes("inject")) return "inject";
    if (s.includes("detect")) return "detect";
    if (s.includes("context") || s.includes("blast")) return "context";
    if (s.includes("rca") || s.includes("memory") || s.includes("correlate")) return "rca";
    if (s.includes("policy") || s.includes("approval") || s.includes("withheld")) return "policy";
    if (s.includes("act") || s.includes("shadow") || s.includes("fix") || s.includes("restore")) return "act";
    if (s.includes("validate") || s.includes("rollback")) return "validate";
    if (s.includes("resolve") || s.includes("contain") || s.includes("escalate") || s.includes("cost") || s.includes("store")) return "resolve";
    return "act";
  };

  const handleInject = async () => {
    if (!selectedId) return;
    setInjecting(true);
    setError(null);
    setResult(null);
    setParsedLogs([]);
    setCompletedStages(new Set());
    setActiveStageId("system");

    const url = `${API_URL}/actions/drill/${selectedId}/stream`;

    const initialResult: ChaosDrillResult = {
      success: false,
      scenarioId: selectedId,
      scenarioName: activeScenario?.name || selectedId,
      status: "running",
      incidentId: null,
      signalType: null,
      assetUrn: null,
      summary: null,
      rootCauseAsset: null,
      rootCauseColumn: null,
      actionsTaken: [],
      pr: null,
      changeType: null,
      log: [],
      error: null,
    };

    setResult({ ...initialResult });

    try {
      const res = await fetch(url);
      if (!res.ok || !res.body) {
        throw new Error(`Streaming failed: HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      const currentCompleted = new Set<string>();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice("data: ".length);
            try {
              const msg = JSON.parse(dataStr);
              const now = new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

              if (msg.type === "log") {
                const stageId = mapStageToTimeline(msg.stage);
                setActiveStageId(stageId);
                currentCompleted.add(stageId);
                setCompletedStages(new Set(currentCompleted));

                setParsedLogs((prev) => [
                  ...prev,
                  {
                    id: Math.random().toString(36).substring(2, 9),
                    stage: msg.stage,
                    message: msg.message,
                    timestamp: now,
                  },
                ]);
                initialResult.log.push(`[${msg.stage}] ${msg.message}`);
                setResult({ ...initialResult });
              } else if (msg.type === "incident") {
                initialResult.incidentId = msg.incident_id;
                initialResult.signalType = msg.signal_type;
                initialResult.assetUrn = msg.asset_urn || null;
                initialResult.summary = msg.summary || null;
                initialResult.status = "detected";
                setResult({ ...initialResult });
              } else if (msg.type === "done") {
                initialResult.success = msg.success;
                initialResult.status = msg.status;
                initialResult.incidentId = msg.incident_id || initialResult.incidentId;
                initialResult.signalType = msg.signal_type || initialResult.signalType;
                initialResult.assetUrn = msg.asset_urn || initialResult.assetUrn;
                initialResult.rootCauseAsset = msg.root_cause_asset;
                initialResult.rootCauseColumn = msg.root_cause_column;
                initialResult.actionsTaken = msg.actions_taken || [];
                initialResult.pr = msg.pr;
                initialResult.changeType = msg.change_type;

                currentCompleted.add("resolve");
                setCompletedStages(new Set(currentCompleted));
                setActiveStageId("resolve");

                setResult({ ...initialResult });
                if (onDrillComplete) onDrillComplete(initialResult);
              } else if (msg.type === "error") {
                initialResult.error = msg.error;
                initialResult.status = "failed";
                setResult({ ...initialResult });
                setError(msg.error);
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to execute chaos drill";
      setError(msg);
      if (initialResult) {
        initialResult.error = msg;
        initialResult.status = "failed";
        setResult({ ...initialResult });
      }
    } finally {
      setInjecting(false);
    }
  };

  const isStreamingView = injecting || result !== null || error !== null;

  return (
    <div
      style={{ zIndex: 9999 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-3 md:p-6 backdrop-blur-md transition-all duration-300"
    >
      <div className="card w-full max-w-5xl bg-[#090b0e] border-border-strong text-foreground shadow-2xl overflow-hidden flex flex-col max-h-[92vh] rounded-2xl border">
        {/* Top High-Tech Command Bar */}
        <div className="flex items-center justify-between border-b border-border/80 bg-surface/90 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-bad/15 border border-bad/30 text-bad font-black text-base shadow-[0_0_15px_rgba(208,59,59,0.25)]">
              ⚡
              {injecting && (
                <span className="absolute -top-1 -right-1 flex h-3 w-3">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-accent"></span>
                </span>
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold tracking-wide text-foreground">
                  Production Chaos & Autonomous Self-Healing Simulator
                </h2>
                <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-mono font-medium text-accent border border-accent/30">
                  Sentinel v1.4
                </span>
              </div>
              <p className="text-xs text-muted">
                Inject controlled failures, watch graph causality tracing, and verify automated remediation in real time.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {isStreamingView && (
              <div className="hidden sm:flex items-center gap-2 rounded-lg border border-border bg-surface-raised px-3 py-1 text-xs font-mono text-muted">
                <span className={`inline-block h-2 w-2 rounded-full ${injecting ? "bg-accent animate-pulse" : result?.success ? "bg-good" : "bg-warn"}`} />
                <span>{injecting ? `STREAMING LIVE: ${elapsedSeconds}s` : `DRILL FINISHED (${elapsedSeconds}s)`}</span>
              </div>
            )}
            <button
              onClick={onClose}
              disabled={injecting}
              className="rounded-lg border border-border/60 bg-surface-raised/80 p-2 text-muted hover:bg-surface-hover hover:text-foreground transition disabled:opacity-50"
              title="Close modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {loading ? (
            <div className="py-16 text-center space-y-3">
              <div className="mx-auto h-8 w-8 rounded-full border-2 border-accent border-t-transparent animate-spin" />
              <p className="text-xs text-muted font-mono tracking-wider uppercase">Loading Chaos Scenarios & Telemetry Graph...</p>
            </div>
          ) : !isStreamingView ? (
            /* ========================================================================= */
            /* PHASE 1: SCENARIO SELECTOR VIEW                                          */
            /* ========================================================================= */
            <div className="space-y-6">
              {/* Category Filter Pills & Search */}
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    onClick={() => setActiveCategory("all")}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                      activeCategory === "all"
                        ? "bg-accent text-white shadow-sm"
                        : "bg-surface-raised text-muted hover:text-foreground border border-border"
                    }`}
                  >
                    All ({scenarios.length})
                  </button>
                  {categories.map((cat) => {
                    const info = getCategoryInfo(cat);
                    return (
                      <button
                        key={cat}
                        onClick={() => setActiveCategory(cat)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 transition ${
                          activeCategory === cat
                            ? "bg-accent text-white shadow-sm"
                            : "bg-surface-raised text-muted hover:text-foreground border border-border"
                        }`}
                      >
                        <span>{info.icon}</span>
                        <span>{info.label}</span>
                      </button>
                    );
                  })}
                </div>

                <div className="relative">
                  <input
                    type="text"
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                    placeholder="Search scenarios..."
                    className="w-full sm:w-56 rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
                  />
                  {searchFilter && (
                    <button
                      onClick={() => setSearchFilter("")}
                      className="absolute right-2.5 top-1.5 text-xs text-muted hover:text-foreground"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>

              {/* Scenario Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[380px] overflow-y-auto pr-1">
                {filteredScenarios.map((s) => {
                  const isSelected = s.id === selectedId;
                  const catInfo = getCategoryInfo(s.category);

                  return (
                    <div
                      key={s.id}
                      onClick={() => setSelectedId(s.id)}
                      className={`cursor-pointer rounded-xl border p-4 transition-all duration-200 flex flex-col justify-between space-y-3 ${
                        isSelected
                          ? "border-accent bg-accent/10 shadow-[0_0_20px_rgba(57,135,229,0.15)] ring-1 ring-accent"
                          : "border-border bg-surface-raised/60 hover:border-border-strong hover:bg-surface-raised"
                      }`}
                    >
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold border uppercase ${catInfo.color}`}>
                            <span>{catInfo.icon}</span>
                            <span>{s.category || "Scenario"}</span>
                          </span>
                          <span className="font-mono text-[10px] text-muted-dim">ID: {s.id}</span>
                        </div>
                        <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                          {isSelected && <span className="text-accent">✓</span>}
                          {s.name}
                        </h3>
                        <p className="text-[11px] text-muted leading-relaxed line-clamp-2">{s.description}</p>
                      </div>

                      <div className="pt-2 border-t border-border/50 flex items-center justify-between text-[10px] text-muted font-mono">
                        <div className="flex items-center gap-1.5">
                          <span className="text-muted-dim">Signal:</span>
                          <span className="text-foreground">{s.signalType}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-muted-dim">Target:</span>
                          <span className="text-foreground truncate max-w-[120px]">{s.expectedRootCause || "raw_transactions"}</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Selected Scenario Detailed Inspector */}
              {activeScenario && (
                <div className="rounded-xl border border-border bg-surface-raised/40 p-4 space-y-3 text-xs">
                  <div className="flex items-center justify-between border-b border-border/60 pb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-accent font-mono text-[11px]">ACTIVE SELECTION:</span>
                      <span className="font-semibold text-foreground">{activeScenario.name}</span>
                    </div>
                    <span className="font-mono text-[11px] text-muted">ID: {activeScenario.id}</span>
                  </div>

                  <p className="text-muted text-xs leading-relaxed">{activeScenario.description}</p>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                    <div className="rounded-lg bg-black/40 border border-border/60 p-2.5">
                      <span className="text-muted-dim block text-[10px] uppercase font-mono">Expected Signal</span>
                      <span className="font-mono text-cyan-400 font-medium">{activeScenario.signalType}</span>
                    </div>
                    <div className="rounded-lg bg-black/40 border border-border/60 p-2.5">
                      <span className="text-muted-dim block text-[10px] uppercase font-mono">Target Asset / Node</span>
                      <span className="font-mono text-amber-400 font-medium">{activeScenario.expectedRootCause || "raw_transactions"}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Warning Callout */}
              <div className="rounded-xl border border-warn/30 bg-warn-soft/10 p-3.5 text-xs text-muted flex items-start gap-3">
                <span className="text-base text-warn shrink-0">⚠️</span>
                <p className="text-[11px] leading-relaxed">
                  Executing this drill triggers real fault injection in DuckDB & dbt, exercises the AST lineage engine, fires DataHub telemetry alerts, and invokes the autonomous Sentinel LLM Agent to remediate and write back post-mortems.
                </p>
              </div>

              {/* Bottom Action Footer */}
              <div className="flex items-center justify-between pt-2 border-t border-border">
                <span className="text-xs text-muted font-mono">{scenarios.length} Production Scenarios Ready</span>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-lg border border-border bg-surface-raised px-4 py-2 text-xs font-medium text-muted hover:text-foreground hover:bg-surface-hover transition"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleInject}
                    className="rounded-lg bg-bad hover:bg-bad/90 px-5 py-2 text-xs font-bold text-white shadow-lg shadow-bad/20 hover:shadow-bad/30 transition flex items-center gap-2"
                  >
                    <span>⚡</span>
                    <span>Launch Fire Drill</span>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            /* ========================================================================= */
            /* PHASE 2: AGENTIC LIVE STREAMING INTERFACE                                */
            /* ========================================================================= */
            <div className="space-y-5">
              {/* Scenario Context Header */}
              <div className="flex flex-wrap items-center justify-between gap-3 bg-surface-raised/60 border border-border rounded-xl px-4 py-3">
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-bad/20 text-bad font-bold text-sm">
                    ⚡
                  </span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-xs font-semibold text-foreground">{result?.scenarioName || selectedId}</h3>
                      <span className="rounded bg-black/50 px-2 py-0.5 text-[10px] font-mono text-muted border border-border">
                        {selectedId}
                      </span>
                    </div>
                    <p className="text-[11px] text-muted truncate max-w-md">{activeScenario?.description}</p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {!injecting && (
                    <button
                      onClick={handleResetToSetup}
                      className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted hover:text-foreground hover:bg-surface-hover transition"
                    >
                      ← Select Different Scenario
                    </button>
                  )}
                  {result?.incidentId && (
                    <Link
                      href={`/incidents/${result.incidentId}`}
                      target="_blank"
                      className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90 transition flex items-center gap-1"
                    >
                      <span>View Full Incident Graph</span>
                      <span>↗</span>
                    </Link>
                  )}
                </div>
              </div>

              {/* Real-time Agentic Stage Timeline */}
              <div className="rounded-xl border border-border bg-surface-raised/40 p-4 space-y-3">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-mono text-muted uppercase tracking-wider font-medium">Autonomous Remediation Lifecycle</span>
                  <span className="font-mono text-accent">
                    {injecting ? "LOOP IN PROGRESS" : result?.success ? "GATE VERIFIED GREEN" : "LOOP TERMINATED"}
                  </span>
                </div>

                <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-9 gap-1.5">
                  {STAGES.map((st, idx) => {
                    const isDone = completedStages.has(st.id);
                    const isCurrent = activeStageId === st.id && injecting;

                    return (
                      <div
                        key={st.id}
                        className={`rounded-lg border p-2 text-center transition-all duration-300 flex flex-col items-center justify-center gap-1 ${
                          isDone && !isCurrent
                            ? "border-good/40 bg-good-soft/20 text-good"
                            : isCurrent
                            ? "border-accent bg-accent/20 text-accent shadow-[0_0_12px_rgba(57,135,229,0.3)] animate-pulse"
                            : "border-border/60 bg-black/30 text-muted-dim"
                        }`}
                      >
                        <div className="flex items-center gap-1">
                          <span className="text-xs">{isDone && !isCurrent ? "✓" : st.icon}</span>
                          <span className="text-[10px] font-mono opacity-60">{idx + 1}</span>
                        </div>
                        <span className="text-[10px] font-medium leading-tight line-clamp-1">{st.label}</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Telemetry & Agent Intel HUD Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
                <div className="rounded-xl border border-border bg-surface-raised/80 p-3 space-y-1">
                  <span className="text-[10px] font-mono uppercase text-muted-dim block">Active Incident</span>
                  <p className="font-mono font-bold text-accent text-xs">
                    {result?.incidentId ? (
                      <span className="flex items-center gap-1.5">
                        <span className="inline-block h-2 w-2 rounded-full bg-accent animate-ping" />
                        {result.incidentId}
                      </span>
                    ) : injecting ? (
                      <span className="text-muted animate-pulse">Detecting...</span>
                    ) : (
                      "N/A"
                    )}
                  </p>
                </div>

                <div className="rounded-xl border border-border bg-surface-raised/80 p-3 space-y-1">
                  <span className="text-[10px] font-mono uppercase text-muted-dim block">Signal Type</span>
                  <p className="font-mono text-cyan-400 text-xs truncate">
                    {result?.signalType || (injecting ? "Scanning assertions..." : "None")}
                  </p>
                </div>

                <div className="rounded-xl border border-border bg-surface-raised/80 p-3 space-y-1">
                  <span className="text-[10px] font-mono uppercase text-muted-dim block">Target Asset</span>
                  <p className="font-mono text-amber-400 text-xs truncate" title={result?.assetUrn || ""}>
                    {result?.assetUrn ? result.assetUrn.split(",").slice(-2, -1)[0] || result.assetUrn : activeScenario?.expectedRootCause || "raw_transactions"}
                  </p>
                </div>

                <div className="rounded-xl border border-border bg-surface-raised/80 p-3 space-y-1">
                  <span className="text-[10px] font-mono uppercase text-muted-dim block">Resolution Status</span>
                  <p className={`font-mono font-bold text-xs uppercase ${
                    result?.success ? "text-good" : result?.error ? "text-bad" : result?.status === "detected" ? "text-warn" : "text-muted"
                  }`}>
                    {result?.status || (injecting ? "Injecting" : "Ready")}
                  </p>
                </div>
              </div>

              {/* Agent Terminal Log Console */}
              <div className="rounded-xl border border-border-strong bg-[#050608] shadow-2xl overflow-hidden font-mono text-xs flex flex-col h-72">
                {/* Terminal Header */}
                <div className="flex items-center justify-between px-3.5 py-2 bg-[#0c0e12] border-b border-border/80 text-[11px] text-muted select-none">
                  <div className="flex items-center gap-2">
                    <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500/80" />
                    <span className="inline-block h-2.5 w-2.5 rounded-full bg-yellow-500/80" />
                    <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500/80" />
                    <span className="ml-2 font-mono text-[10px] text-muted-dim tracking-wider">
                      sentinel-agent // sse-event-stream // worker-01
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-1.5 cursor-pointer text-[10px]">
                      <input
                        type="checkbox"
                        checked={autoScroll}
                        onChange={(e) => setAutoScroll(e.target.checked)}
                        className="rounded border-border bg-surface text-accent"
                      />
                      <span>Auto-scroll</span>
                    </label>
                    <button
                      onClick={handleCopyLogs}
                      className="rounded border border-border/60 bg-surface-raised px-2 py-0.5 text-[10px] text-muted hover:text-foreground transition"
                    >
                      {copiedLogs ? "Copied! ✓" : "Copy Logs"}
                    </button>
                  </div>
                </div>

                {/* Terminal Log Stream */}
                <div className="flex-1 overflow-y-auto p-3.5 space-y-1 text-[11px] leading-relaxed scrollbar-thin">
                  {parsedLogs.length === 0 ? (
                    <div className="py-10 text-center text-muted-dim space-y-2 font-mono">
                      <div className="h-5 w-5 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto" />
                      <p>Initializing agent loop & connecting SSE telemetry channel...</p>
                    </div>
                  ) : (
                    parsedLogs.map((log) => (
                      <div key={log.id} className="flex items-start gap-2 group hover:bg-white/[0.02] py-0.5 rounded px-1">
                        <span className="text-muted-dim select-none shrink-0 text-[10px]">{log.timestamp}</span>
                        <span className={`shrink-0 rounded border px-1.5 py-0 text-[10px] font-semibold uppercase ${getStageBadgeColor(log.stage)}`}>
                          {log.stage}
                        </span>
                        <span className="text-foreground/90 break-all">{log.message}</span>
                      </div>
                    ))
                  )}

                  {injecting && (
                    <div className="flex items-center gap-2 text-accent text-[11px] pt-1">
                      <span className="inline-block h-2 w-2 rounded-full bg-accent animate-ping" />
                      <span className="animate-pulse">Sentinel Agent executing self-healing loop...</span>
                    </div>
                  )}
                  <div ref={terminalEndRef} />
                </div>
              </div>

              {/* Outcome Completion Banner */}
              {result && !injecting && (
                <div className={`rounded-xl border p-4 text-xs transition-all duration-300 space-y-3 ${
                  result.success
                    ? "border-good/40 bg-good-soft/20 text-foreground"
                    : result.error
                    ? "border-bad/40 bg-bad-soft/20 text-foreground"
                    : "border-warn/40 bg-warn-soft/20 text-foreground"
                }`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{result.success ? "✅" : result.error ? "❌" : "🛡️"}</span>
                      <div>
                        <h4 className={`font-bold ${result.success ? "text-good" : result.error ? "text-bad" : "text-warn"}`}>
                          {result.success
                            ? "Autonomous Self-Healing Completed Successfully"
                            : result.error
                            ? "Fire Drill Failed"
                            : "Incident Detected & Contained"}
                        </h4>
                        <p className="text-[11px] text-muted">
                          {result.success
                            ? "All validation assertions returned green after journaled mitigation was applied."
                            : result.error
                            ? result.error
                            : "Protective bounds applied to warehouse & graph, awaiting human sign-off."}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleResetToSetup}
                        className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted hover:text-foreground transition"
                      >
                        Run Another Drill
                      </button>
                      {result.incidentId && (
                        <Link
                          href={`/incidents/${result.incidentId}`}
                          className="rounded-lg bg-accent px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent/90 transition shadow"
                        >
                          View Incident Details →
                        </Link>
                      )}
                    </div>
                  </div>

                  {/* Interventions applied summary */}
                  {result.actionsTaken && result.actionsTaken.length > 0 && (
                    <div className="pt-2 border-t border-border/40 flex items-center gap-2 text-[11px]">
                      <span className="text-muted font-mono">Actions Executed:</span>
                      <div className="flex flex-wrap gap-1.5">
                        {result.actionsTaken.map((act, i) => (
                          <span key={i} className="rounded bg-black/40 border border-border/80 px-2 py-0.5 font-mono text-accent">
                            {act}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* PR Generated link if available */}
                  {result.pr && (
                    <div className="pt-2 border-t border-border/40 flex items-center gap-2 text-[11px]">
                      <span className="text-muted font-mono">Remediation PR:</span>
                      <code className="text-emerald-400 font-mono">{result.pr}</code>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
