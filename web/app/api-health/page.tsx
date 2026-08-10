"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import StatTile from "@/components/StatTile";
import { SkeletonRows, SkeletonTile } from "@/components/Skeleton";
import {
  fetchApiHealthStats,
  fetchDependencies,
  fetchAdvisories,
  fetchMigrations,
  fetchBlastRadius,
  triggerDependencyScan,
  syncRegistries,
  remediateAdvisory,
} from "@/lib/queries";
import { API_URL } from "@/lib/graphql";
import type {
  Advisory,
  ApiHealthStats,
  BlastRadius,
  Dependency,
  Migration,
  RemediateAdvisoryResult,
} from "@/lib/types";

const POLL_MS = 15_000;

type TabKey = "advisories" | "dependencies" | "migrations" | "blast-radius";

export default function ApiHealthPage() {
  const [stats, setStats] = useState<ApiHealthStats | null>(null);
  const [dependencies, setDependencies] = useState<Dependency[]>([]);
  const [advisories, setAdvisories] = useState<Advisory[]>([]);
  const [migrations, setMigrations] = useState<Migration[]>([]);
  const [activeTab, setActiveTab] = useState<TabKey>("advisories");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [remediating, setRemediating] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  // Search & Filters
  const [depQuery, setDepQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  // Selected package for blast radius
  const [selectedPkg, setSelectedPkg] = useState<string>("scikit-learn");
  const [blastRadius, setBlastRadius] = useState<BlastRadius | null>(null);
  const [loadingBlast, setLoadingBlast] = useState(false);

  // Selected migration for diff viewer modal
  const [selectedMigration, setSelectedMigration] = useState<Migration | null>(null);

  // Active Remediation Modal State with Multi-File Streaming
  const [remediationModal, setRemediationModal] = useState<{
    open: boolean;
    adv: Advisory;
    stage: "analyzing" | "synthesizing" | "validating" | "completed" | "error";
    activeFile: string;
    files: Record<string, { code: string; diff?: string; done?: boolean }>;
    error?: string;
    result?: RemediateAdvisoryResult | null;
  } | null>(null);



  const loadData = () => {
    Promise.all([
      fetchApiHealthStats(),
      fetchDependencies(),
      fetchAdvisories(),
      fetchMigrations(),
    ])
      .then(([st, deps, advs, migs]) => {
        setStats(st);
        setDependencies(deps);
        setAdvisories(advs);
        setMigrations(migs);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, POLL_MS);
    return () => clearInterval(id);
  }, []);

  // Load blast radius whenever selected package changes
  useEffect(() => {
    if (!selectedPkg) return;
    let active = true;
    fetchBlastRadius(selectedPkg)
      .then((data) => {
        if (active) setBlastRadius(data);
      })
      .catch(() => {
        if (active) setBlastRadius(null);
      })
      .finally(() => {
        if (active) setLoadingBlast(false);
      });
    return () => {
      active = false;
    };
  }, [selectedPkg]);

  const handleScanNow = async () => {
    setScanning(true);
    setScanMessage(null);
    try {
      const res = await triggerDependencyScan();
      if (res.scanned) {
        setScanMessage(
          `Scan complete: ${res.advisoriesChecked} advisories evaluated, ${res.incidentsFound} affected package usage(s) flagged.`
        );
      } else {
        setScanMessage(`Scan error: ${res.error || "Unknown failure"}`);
      }
      loadData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to run scan";
      setScanMessage(`Scan failed: ${msg}`);
    } finally {
      setScanning(false);
    }
  };

  const handleSyncRegistries = async () => {
    setSyncing(true);
    setScanMessage(null);
    try {
      const res = await syncRegistries();
      if (res.success) {
        const netStatus = res.networkOnline ? "Live PyPI Registry Online" : "Offline Registry Cache";
        setScanMessage(
          `Registry sync complete (${netStatus}): ${res.packagesChecked} packages checked, ${res.advisoriesGenerated} breaking changes auto-detected.`
        );
      } else {
        setScanMessage(`Registry sync standby: ${res.error || "Standby"}. Manual Webhook ingestion is active.`);
      }
      loadData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Sync failed";
      setScanMessage(`Registry monitor: ${msg}. Manual Webhook trigger is active.`);
    } finally {
      setSyncing(false);
    }
  };

  const handleAutoRemediate = async (adv: Advisory) => {
    const initialFile = adv.usages[0]?.file || "ml/train.py";
    setRemediating(true);
    setRemediationModal({
      open: true,
      adv,
      stage: "analyzing",
      activeFile: initialFile,
      files: {
        [initialFile]: { code: "", done: false },
      },
    });

    try {
      const resStream = await fetch(`${API_URL}/api/v1/advisories/${adv.id}/stream-remediation`);
      if (!resStream.ok || !resStream.body) {
        const res = await remediateAdvisory(adv.id);
        if (!res.success) throw new Error(res.error || "Remediation failed");
        setRemediationModal((prev) => (prev ? { ...prev, stage: "completed", result: res } : null));
        setAdvisories((prev) => prev.filter((a) => a.id !== adv.id));
        setStats((prev) =>
          prev
            ? {
                ...prev,
                activeAdvisories: Math.max(0, prev.activeAdvisories - 1),
                resolvedMigrations: prev.resolvedMigrations + 1,
              }
            : null
        );
        loadData();
        return;
      }

      const reader = resStream.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const evt of events) {
          if (!evt.startsWith("data: ")) continue;
          const jsonStr = evt.replace("data: ", "").trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            if (data.type === "step") {
              setRemediationModal((prev) => (prev ? { ...prev, stage: data.stage } : null));
            } else if (data.type === "file_start") {
              setRemediationModal((prev) =>
                prev
                  ? {
                      ...prev,
                      stage: "synthesizing",
                      activeFile: data.file,
                      files: {
                        ...prev.files,
                        [data.file]: prev.files[data.file] || { code: "", done: false },
                      },
                    }
                  : null
              );
            } else if (data.type === "token") {
              setRemediationModal((prev) => {
                if (!prev) return null;
                const f = data.file || prev.activeFile;
                const current = prev.files[f] || { code: "", done: false };
                return {
                  ...prev,
                  stage: "synthesizing",
                  activeFile: f,
                  files: {
                    ...prev.files,
                    [f]: { ...current, code: current.code + data.token },
                  },
                };
              });
            } else if (data.type === "file_done") {
              setRemediationModal((prev) => {
                if (!prev) return null;
                const f = data.file || prev.activeFile;
                const current = prev.files[f] || { code: "", done: false };
                return {
                  ...prev,
                  files: {
                    ...prev.files,
                    [f]: { ...current, done: true, diff: data.diff },
                  },
                };
              });
            } else if (data.type === "complete") {
              setRemediationModal((prev) =>
                prev
                  ? {
                      ...prev,
                      stage: "completed",
                      result: {
                        success: true,
                        incidentId: data.incident_id,
                        package: data.package,
                        pr: null,
                        diffPath: null,
                        diffPreview: data.diff,
                        filesModified: data.files_modified,
                        error: null,
                      },
                    }
                  : null
              );

              setAdvisories((prev) => prev.filter((a) => a.id !== adv.id));
              setStats((prev) =>
                prev
                  ? {
                      ...prev,
                      activeAdvisories: Math.max(0, prev.activeAdvisories - 1),
                      resolvedMigrations: prev.resolvedMigrations + 1,
                    }
                  : null
              );
              loadData();
            } else if (data.type === "error") {
              throw new Error(data.error || "Remediation failed");
            }
          } catch {
            // Ignore partial chunks
          }
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Remediation failed";
      setRemediationModal((prev) => (prev ? { ...prev, stage: "error", error: msg } : null));
    } finally {
      setRemediating(false);
    }
  };



  const filteredDeps = useMemo(() => {
    let rows = dependencies;
    if (statusFilter !== "all") {
      rows = rows.filter((d) => d.status === statusFilter);
    }
    if (depQuery.trim()) {
      const q = depQuery.toLowerCase();
      rows = rows.filter(
        (d) =>
          d.package.toLowerCase().includes(q) ||
          (d.installedVersion ?? "").toLowerCase().includes(q)
      );
    }
    return rows;
  }, [dependencies, statusFilter, depQuery]);

  return (
    <div className="px-8 py-7 space-y-7">
      <PageHeader
        title="Self-Maintaining APIs"
        subtitle="Automated API change intelligence, DataHub lineage blast-radius mapping, and autonomous migration PRs."
        live={!error}
        actions={
          <div className="flex items-center gap-2.5">
            <button
              onClick={handleSyncRegistries}
              disabled={syncing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent hover:border-accent hover:bg-accent-soft/80 disabled:opacity-50 transition"
              title="Automatically query PyPI / GitHub for latest releases and breaking changes"
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={syncing ? "animate-spin" : ""}
              >
                <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" />
                <path d="M12 12v9" />
                <path d="m8 17 4 4 4-4" />
              </svg>
              <span>{syncing ? "Syncing PyPI..." : "Auto-Sync PyPI/GitHub"}</span>
            </button>



            <button
              onClick={handleScanNow}
              disabled={scanning}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-1.5 text-xs font-medium text-white shadow-sm hover:opacity-90 disabled:opacity-50 transition"
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={scanning ? "animate-spin" : ""}
              >
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 21h5v-5" />
              </svg>
              <span>{scanning ? "Scanning..." : "SRE Scan Now"}</span>
            </button>
          </div>
        }
      />

      {error && (
        <div className="card border-bad/40 p-4 text-sm text-bad bg-bad-soft/40">
          Cannot reach API backend. Ensure <code>python -m agent serve</code> or <code>python -m api</code> is running on port 8090.
        </div>
      )}

      {scanMessage && (
        <div className="card border-accent/40 bg-accent-soft/30 p-3.5 text-xs text-foreground flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-accent animate-pulse" />
            <span>{scanMessage}</span>
          </div>
          <button
            onClick={() => setScanMessage(null)}
            className="text-muted hover:text-foreground text-xs"
          >
            ✕
          </button>
        </div>
      )}

      {/* KPI Tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {loading ? (
          <>
            <SkeletonTile />
            <SkeletonTile />
            <SkeletonTile />
            <SkeletonTile />
          </>
        ) : (
          <>
            <StatTile
              label="Watched Packages"
              value={stats?.totalDependencies ?? dependencies.length}
              tone="good"
              hint="AST-indexed across repository"
            />
            <StatTile
              label="Active Advisories"
              value={stats?.activeAdvisories ?? advisories.length}
              tone={stats && stats.activeAdvisories > 0 ? "warn" : "good"}
              hint={stats && stats.activeAdvisories > 0 ? "breaking changes detected" : "all up to date"}
            />
            <StatTile
              label="Auto-Applied Migrations"
              value={stats?.resolvedMigrations ?? 0}
              tone="good"
              hint={`${stats?.pendingMigrations ?? 0} pending PR review`}
            />
            <StatTile
              label="Affected Code Usages"
              value={stats?.totalAffectedUsages ?? 0}
              tone={stats && stats.totalAffectedUsages > 0 ? "bad" : "good"}
              hint="call-sites in direct pipeline path"
            />
          </>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-border flex items-center justify-between">
        <div className="flex gap-2">
          {[
            { key: "advisories", label: `Active Advisories (${advisories.length})` },
            { key: "dependencies", label: `Dependency Inventory (${dependencies.length})` },
            { key: "migrations", label: `Migration History (${migrations.length})` },
            { key: "blast-radius", label: "Lineage Blast Radius" },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as TabKey)}
              className={`pb-3 px-3 text-xs font-medium border-b-2 transition ${
                activeTab === tab.key
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <span className="text-[11px] text-muted-dim pb-3">
          Powered by Sentinel AST Engine + DataHub Lineage
        </span>
      </div>

      {/* TAB 1: ACTIVE ADVISORIES */}
      {activeTab === "advisories" && (
        <div className="space-y-4">
          {advisories.length === 0 ? (
            <div className="card p-10 text-center space-y-3">
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-surface-raised border border-border text-muted">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
                  <path d="m9 12 2 2 4-4" />
                </svg>
              </div>
              <p className="text-sm font-medium">No Active Breaking Changes Detected</p>
              <p className="text-xs text-muted max-w-md mx-auto">
                No external API or dependency breaking changes have been reported. When a vendor publishes an advisory or the registry monitor detects one, Sentinel maps affected files and DataHub downstream assets.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {advisories.map((adv) => (
                <div key={adv.id} className="card card-accent p-5 space-y-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-bad-soft px-2 py-0.5 font-mono text-[11px] font-semibold text-bad uppercase">
                          {adv.kind.replace("_", " ")}
                        </span>
                        <h3 className="text-sm font-semibold">{adv.package}</h3>
                        <span className="font-mono text-xs text-muted">
                          {adv.fromVersion} → <span className="text-warn">{adv.toVersion}</span>
                        </span>
                        <span className="rounded bg-surface-raised border border-border px-2 py-0.5 font-mono text-[10px] text-muted-dim">
                          auto-monitored
                        </span>
                      </div>
                      <p className="mt-1.5 text-xs text-foreground font-medium">{adv.summary}</p>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => {
                          setSelectedPkg(adv.package);
                          setActiveTab("blast-radius");
                        }}
                        className="rounded-md border border-border bg-surface-raised px-2.5 py-1 text-xs text-muted hover:text-foreground transition"
                      >
                        Blast Radius ({adv.impactedCount} assets) →
                      </button>
                      <button
                        onClick={() => handleAutoRemediate(adv)}
                        disabled={remediating}
                        className="rounded-md bg-accent px-2.5 py-1 text-xs text-white hover:opacity-90 disabled:opacity-50 transition flex items-center gap-1.5"
                      >
                        {remediating && <span className="h-2 w-2 rounded-full bg-white animate-ping" />}
                        <span>{remediating ? "Remediating..." : "Auto-Remediate"}</span>
                      </button>
                    </div>
                  </div>

                  {adv.migration && (
                    <div className="rounded-lg border border-border bg-surface-raised/80 p-3 text-xs">
                      <p className="font-medium text-foreground mb-1">Required Migration Action:</p>
                      <p className="text-muted leading-relaxed">{adv.migration}</p>
                    </div>
                  )}

                  {/* Impacted Usages */}
                  {adv.usages && adv.usages.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-dim">
                        Codebase Usages Affected ({adv.usages.length})
                      </p>
                      <div className="space-y-1.5 max-h-48 overflow-y-auto scrollbar-thin">
                        {adv.usages.map((u, idx) => (
                          <div
                            key={idx}
                            className="flex items-center justify-between rounded border border-border bg-surface px-3 py-1.5 text-xs font-mono"
                          >
                            <span className="text-accent">{u.file}:{u.line}</span>
                            <span className="text-muted truncate max-w-[65%]">{u.code}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Impacted DataHub Assets */}
                  {adv.impactedAssets && adv.impactedAssets.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-border">
                      <span className="text-[11px] text-muted-dim mr-1">DataHub Lineage Impact:</span>
                      {adv.impactedAssets.map((asset, i) => (
                        <span
                          key={i}
                          className="rounded bg-surface-raised border border-border px-2 py-0.5 font-mono text-[10px] text-muted truncate max-w-xs"
                        >
                          {asset.split(",")[1]?.replace(")", "") || asset}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: DEPENDENCY INVENTORY */}
      {activeTab === "dependencies" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <input
              type="text"
              value={depQuery}
              onChange={(e) => setDepQuery(e.target.value)}
              placeholder="Search package or version..."
              className="w-72 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs outline-none focus:border-accent"
            />

            <div className="flex gap-1.5">
              {["all", "at_risk", "healthy"].map((st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  className={`rounded-full border px-3 py-0.5 text-xs capitalize transition ${
                    statusFilter === st
                      ? "border-accent bg-accent-soft text-accent"
                      : "border-border text-muted hover:text-foreground"
                  }`}
                >
                  {st.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          <div className="card overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-dim">
                  <th className="px-4 py-3 font-medium">Package</th>
                  <th className="px-4 py-3 font-medium">Installed Version</th>
                  <th className="px-4 py-3 font-medium text-center">Files Using</th>
                  <th className="px-4 py-3 font-medium text-center">Impacted Assets</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={6} className="p-4">
                      <SkeletonRows rows={5} />
                    </td>
                  </tr>
                ) : filteredDeps.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-muted">
                      No packages match current query.
                    </td>
                  </tr>
                ) : (
                  filteredDeps.map((dep) => (
                    <tr
                      key={dep.package}
                      className="border-b border-border last:border-0 hover:bg-surface-raised transition"
                    >
                      <td className="px-4 py-3 font-mono font-medium text-foreground">
                        {dep.package}
                      </td>
                      <td className="px-4 py-3 font-mono text-muted">
                        {dep.installedVersion ?? "system/builtin"}
                      </td>
                      <td className="px-4 py-3 text-center tabular-nums">{dep.filesUsing}</td>
                      <td className="px-4 py-3 text-center tabular-nums">{dep.impactedAssets}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            dep.status === "at_risk"
                              ? "bg-bad-soft text-bad"
                              : dep.status === "healthy"
                              ? "bg-good-soft text-good"
                              : "bg-surface-raised text-muted"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              dep.status === "at_risk"
                                ? "bg-bad"
                                : dep.status === "healthy"
                                ? "bg-good"
                                : "bg-muted"
                            }`}
                          />
                          {dep.status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => {
                            setSelectedPkg(dep.package);
                            setActiveTab("blast-radius");
                          }}
                          className="text-xs text-accent hover:underline"
                        >
                          Trace Lineage →
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: MIGRATION HISTORY */}
      {activeTab === "migrations" && (
        <div className="space-y-4">
          {migrations.length === 0 ? (
            <div className="card p-10 text-center space-y-2">
              <p className="text-sm font-medium">No API Migrations on Record</p>
              <p className="text-xs text-muted max-w-md mx-auto">
                When an API breaking change is remediated, the LLM-generated code diff and draft pull request will be indexed here with line-by-line diff inspections.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {migrations.map((mig) => (
                <div key={mig.incidentId} className="card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <Link
                        href={`/incidents/${mig.incidentId}`}
                        className="font-mono text-xs text-accent font-semibold hover:underline"
                      >
                        {mig.incidentId}
                      </Link>
                      <span className="text-xs text-muted">
                        Target Asset: <span className="text-foreground">{mig.assetName ?? mig.assetUrn}</span>
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                          mig.resolved ? "bg-good-soft text-good" : "bg-warn-soft text-warn"
                        }`}
                      >
                        {mig.resolved ? "Resolved / Merged" : "PR Draft Open"}
                      </span>
                      {mig.costUsd != null && (
                        <span className="text-xs text-muted font-mono">
                          ${Math.round(mig.costUsd).toLocaleString()} avoided
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="text-xs text-foreground leading-relaxed">{mig.narrative}</p>

                  <div className="flex items-center justify-between pt-2 border-t border-border text-xs">
                    <span className="text-[11px] text-muted-dim">
                      Detected: {new Date(mig.detectedAt).toLocaleString()}
                    </span>
                    <div className="flex items-center gap-3">
                      {mig.hasDiff && (
                        <button
                          onClick={() => setSelectedMigration(mig)}
                          className="text-xs text-accent hover:underline font-medium"
                        >
                          View Generated Diff →
                        </button>
                      )}
                      {mig.pr && (
                        <a
                          href={mig.pr}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-accent hover:underline font-medium"
                        >
                          View GitHub PR ↗
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 4: LINEAGE BLAST RADIUS */}
      {activeTab === "blast-radius" && (
        <div className="space-y-5">
          <div className="card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">DataHub Lineage Blast Radius Visualizer</h3>
                <p className="text-xs text-muted-dim mt-0.5">
                  Trace how an external API change cascades through source code, training jobs, models, and downstream prediction services.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <label className="text-xs text-muted">Package:</label>
                <select
                  value={selectedPkg}
                  onChange={(e) => setSelectedPkg(e.target.value)}
                  className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-foreground outline-none focus:border-accent"
                >
                  {dependencies.map((d) => (
                    <option key={d.package} value={d.package}>
                      {d.package}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {loadingBlast ? (
              <div className="py-12 text-center text-xs text-muted">Tracing graph lineage...</div>
            ) : !blastRadius ? (
              <div className="py-12 text-center text-xs text-muted">No lineage path discovered.</div>
            ) : (
              <div className="space-y-5">
                {/* Visual Chain */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  {/* Step 1: External API */}
                  <div className="rounded-lg border border-bad/30 bg-bad-soft/20 p-3 space-y-1.5">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-bad">1. External Vendor API</p>
                    <p className="text-xs font-mono font-medium text-foreground">{blastRadius.package}</p>
                    <p className="text-[11px] text-muted-dim">Upstream Package Release</p>
                  </div>

                  {/* Step 2: Source Files */}
                  <div className="rounded-lg border border-warn/30 bg-warn-soft/20 p-3 space-y-1.5">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-warn">2. Repository Code</p>
                    <p className="text-xs font-mono font-medium text-foreground">{blastRadius.files.length} affected file(s)</p>
                    <p className="text-[11px] text-muted-dim">{blastRadius.files.join(", ") || "No direct imports"}</p>
                  </div>

                  {/* Step 3: Direct DataHub Model/Job */}
                  <div className="rounded-lg border border-accent/30 bg-accent-soft/20 p-3 space-y-1.5">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-accent">3. Primary DataHub Asset</p>
                    <p className="text-xs font-mono font-medium text-foreground">{blastRadius.directAssets.length} asset(s)</p>
                    <p className="text-[11px] text-muted-dim truncate">
                      {blastRadius.directAssets[0] ? blastRadius.directAssets[0].split(",")[1]?.replace(")", "") : "None"}
                    </p>
                  </div>

                  {/* Step 4: Downstream Services */}
                  <div className="rounded-lg border border-border bg-surface-raised p-3 space-y-1.5">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">4. Downstream Consumers</p>
                    <p className="text-xs font-mono font-medium text-foreground">{blastRadius.downstreamAssets.length} service(s)</p>
                    <p className="text-[11px] text-muted-dim">Scoring APIs & Dashboard feeds</p>
                  </div>
                </div>

                {/* Details Breakdown */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                  <div className="rounded-lg border border-border bg-surface p-3.5 space-y-2">
                    <p className="text-xs font-medium text-foreground">Direct Code Call-Sites</p>
                    {blastRadius.files.length === 0 ? (
                      <p className="text-xs text-muted">No direct source files import this package.</p>
                    ) : (
                      <ul className="space-y-1 text-xs font-mono text-muted">
                        {blastRadius.files.map((f, i) => (
                          <li key={i} className="flex items-center gap-2">
                            <span className="text-accent">→</span> {f}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="rounded-lg border border-border bg-surface p-3.5 space-y-2">
                    <p className="text-xs font-medium text-foreground">Downstream Lineage Nodes</p>
                    {blastRadius.downstreamAssets.length === 0 ? (
                      <p className="text-xs text-muted">No downstream dependencies registered in DataHub.</p>
                    ) : (
                      <ul className="space-y-1.5 text-xs font-mono text-muted max-h-40 overflow-y-auto scrollbar-thin">
                        {blastRadius.downstreamAssets.map((node, i) => (
                          <li key={i} className="flex items-center justify-between border-b border-border/50 pb-1 last:border-0">
                            <span className="text-foreground">{node.name}</span>
                            <span className="text-[10px] text-muted-dim uppercase">{node.entityType}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* DIFF VIEWER MODAL */}
      {selectedMigration && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6">
          <div className="card w-full max-w-3xl max-h-[85vh] flex flex-col bg-surface border-border-strong p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-sm font-semibold">Automated Migration Diff ({selectedMigration.incidentId})</h3>
                <p className="text-xs text-muted">{selectedMigration.assetName ?? selectedMigration.assetUrn}</p>
              </div>
              <button
                onClick={() => setSelectedMigration(null)}
                className="text-muted hover:text-foreground text-sm"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scrollbar-thin rounded-lg border border-border bg-black/60 p-4 font-mono text-xs">
              <pre className="text-foreground whitespace-pre-wrap leading-relaxed">
                {selectedMigration.diffPreview || "No diff generated."}
              </pre>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-border">
              <button
                onClick={() => setSelectedMigration(null)}
                className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-muted hover:text-foreground"
              >
                Close
              </button>
              {selectedMigration.pr && (
                <a
                  href={selectedMigration.pr}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white hover:opacity-90"
                >
                  Inspect PR on GitHub ↗
                </a>
              )}
            </div>
          </div>
        </div>
      )}


      {/* AUTONOMOUS REMEDIATION LIVE PROGRESS MODAL */}
      {remediationModal?.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-6 backdrop-blur-sm">
          <div className="card w-full max-w-xl bg-surface border-border-strong p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-accent animate-pulse" />
                <h3 className="text-sm font-semibold">
                  Autonomous API Remediation — {remediationModal.adv.package}
                </h3>
              </div>
              {remediationModal.stage === "completed" || remediationModal.stage === "error" ? (
                <button
                  onClick={() => setRemediationModal(null)}
                  className="text-muted hover:text-foreground text-sm"
                >
                  ✕
                </button>
              ) : null}
            </div>

            {/* Stages Timeline */}
            <div className="space-y-3">
              {[
                {
                  id: "analyzing",
                  label: "1. AST Codebase Inspection & DataHub Lineage Mapping",
                  desc: `Found ${remediationModal.adv.usagesCount} call-site(s) across repository.`,
                },
                {
                  id: "synthesizing",
                  label: "2. LLM Backward-Compatible Code Synthesis",
                  desc: "Generating targeted patch avoiding breaking changes.",
                },
                {
                  id: "validating",
                  label: "3. Shadow Environment Sandboxed Validation",
                  desc: "Running AST parser & Python syntax safety gate.",
                },
                {
                  id: "completed",
                  label: "4. Migration Diff & PR Draft Generation",
                  desc: "Advisory resolved and archived into Migration History.",
                },
              ].map((step, idx) => {
                const stageOrder = ["analyzing", "synthesizing", "validating", "completed"];
                const currentIdx = stageOrder.indexOf(remediationModal.stage);
                const stepIdx = stageOrder.indexOf(step.id);
                const isCurrent = remediationModal.stage === step.id;
                const isPassed = (currentIdx > stepIdx && currentIdx !== -1) || remediationModal.stage === "completed";

                return (
                  <div
                    key={idx}
                    className={`flex items-start gap-3 rounded-lg border p-3 text-xs transition ${
                      isCurrent
                        ? "border-accent/50 bg-accent-soft/30 text-foreground"
                        : isPassed
                        ? "border-good/40 bg-good-soft/20 text-foreground"
                        : "border-border/50 bg-surface-raised/40 text-muted opacity-60"
                    }`}
                  >
                    <div className="pt-0.5">
                      {isPassed ? (
                        <span className="text-good font-bold">✓</span>
                      ) : isCurrent ? (
                        <div className="h-3 w-3 rounded-full border-2 border-accent border-t-transparent animate-spin" />
                      ) : (
                        <span className="text-muted font-mono">{idx + 1}</span>
                      )}
                    </div>
                    <div>
                      <p className="font-medium">{step.label}</p>
                      <p className="text-[11px] text-muted mt-0.5">{step.desc}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Multi-File Live Code Writing Terminal */}
            {remediationModal.stage !== "completed" && (
              <div className="space-y-3 rounded-lg border border-border bg-black/95 p-4 font-mono text-xs shadow-2xl">
                {/* File Tabs */}
                <div className="flex items-center justify-between border-b border-border/60 pb-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {Object.entries(remediationModal.files).map(([fileName, fileData]) => {
                      const isActive = remediationModal.activeFile === fileName;
                      return (
                        <button
                          key={fileName}
                          type="button"
                          onClick={() =>
                            setRemediationModal((prev) => (prev ? { ...prev, activeFile: fileName } : null))
                          }
                          className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-medium transition ${
                            isActive
                              ? "bg-accent/20 border border-accent/60 text-foreground"
                              : "bg-surface-raised/40 border border-border/40 text-muted hover:text-foreground"
                          }`}
                        >
                          {fileData.done ? (
                            <span className="text-good font-bold">✓</span>
                          ) : (
                            <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                          )}
                          <span>{fileName}</span>
                        </button>
                      );
                    })}
                  </div>
                  <span className="text-[10px] text-muted font-semibold tracking-wider">
                    {remediationModal.stage === "validating" ? "AST VALIDATING" : "WRITING PATCH"}
                  </span>
                </div>

                {/* Real-time Code Content */}
                <div className="max-h-60 overflow-y-auto scrollbar-thin pt-1 text-muted-foreground whitespace-pre-wrap leading-relaxed text-[11px]">
                  {remediationModal.files[remediationModal.activeFile]?.code ? (
                    <code>{remediationModal.files[remediationModal.activeFile].code}</code>
                  ) : (
                    <span className="text-muted-dim italic">
                      Scanning call-sites and writing backward-compatible changes to {remediationModal.activeFile}...
                    </span>
                  )}
                  <span className="inline-block w-1.5 h-3.5 bg-accent ml-0.5 animate-pulse" />
                </div>
              </div>
            )}

            {/* Error Message */}
            {remediationModal.stage === "error" && (
              <div className="card border-bad/40 bg-bad-soft/30 p-3.5 text-xs text-bad">
                <p className="font-medium">Remediation Failed</p>
                <p className="text-[11px] mt-0.5">{remediationModal.error}</p>
              </div>
            )}

            {/* Completion Result Box */}
            {remediationModal.stage === "completed" && remediationModal.result && (
              <div className="space-y-3 pt-2">
                <div className="rounded-lg border border-good/40 bg-good-soft/20 p-3.5 space-y-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <p className="font-semibold text-good">
                      ✓ Migration Artifact Generated ({remediationModal.result.incidentId})
                    </p>
                    <span className="text-[11px] font-mono text-muted">
                      {remediationModal.result.filesModified} file(s) updated
                    </span>
                  </div>
                  <p className="text-[11px] text-muted">
                    This advisory has been remediated and moved from Active Advisories to Migration History.
                  </p>
                </div>

                <div className="rounded-lg border border-border bg-black/70 p-3 max-h-40 overflow-y-auto font-mono text-[11px] text-muted-foreground scrollbar-thin">
                  <pre className="whitespace-pre-wrap">{remediationModal.result.diffPreview}</pre>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex justify-end gap-2 pt-3 border-t border-border">
              {remediationModal.stage === "completed" ? (
                <>
                  <button
                    onClick={() => {
                      setRemediationModal(null);
                      setActiveTab("migrations");
                    }}
                    className="rounded-lg border border-border bg-surface-raised px-3.5 py-1.5 text-xs font-medium text-foreground hover:bg-surface-hover transition"
                  >
                    View in Migration History →
                  </button>
                  <button
                    onClick={() => setRemediationModal(null)}
                    className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 transition"
                  >
                    Done
                  </button>
                </>
              ) : remediationModal.stage === "error" ? (
                <button
                  onClick={() => setRemediationModal(null)}
                  className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-muted hover:text-foreground"
                >
                  Close
                </button>
              ) : (
                <span className="text-xs text-muted italic flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-accent animate-ping" />
                  Running autonomous remediation...
                </span>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
