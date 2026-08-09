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
  ingestVendorAdvisory,
} from "@/lib/queries";
import type {
  Advisory,
  ApiHealthStats,
  BlastRadius,
  Dependency,
  Migration,
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

  // Ingest Advisory Modal State
  const [showIngestModal, setShowIngestModal] = useState(false);
  const [ingestPkg, setIngestPkg] = useState("scikit-learn");
  const [ingestFrom, setIngestFrom] = useState("1.9.0");
  const [ingestTo, setIngestTo] = useState("2.0.0");
  const [ingestSummary, setIngestSummary] = useState(
    "GradientBoostingClassifier's `n_estimators` renamed to `num_estimators`"
  );
  const [ingestMigration, setIngestMigration] = useState(
    "Rename `n_estimators` keyword argument to `num_estimators`"
  );
  const [ingestSymbols, setIngestSymbols] = useState("GradientBoostingClassifier, n_estimators");
  const [ingestSubmitting, setIngestSubmitting] = useState(false);

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
    setLoadingBlast(true);
    fetchBlastRadius(selectedPkg)
      .then((data) => setBlastRadius(data))
      .catch(() => setBlastRadius(null))
      .finally(() => setLoadingBlast(false));
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

  const handlePublishAdvisory = async (e: React.FormEvent) => {
    e.preventDefault();
    setIngestSubmitting(true);
    try {
      await ingestVendorAdvisory({
        package: ingestPkg.trim(),
        from_version: ingestFrom.trim(),
        to_version: ingestTo.trim(),
        summary: ingestSummary.trim(),
        migration: ingestMigration.trim(),
        symbols: ingestSymbols.split(",").map((s) => s.trim()).filter(Boolean),
        kind: "breaking_change",
      });
      setShowIngestModal(false);
      loadData();
      setSelectedPkg(ingestPkg.trim());
      setActiveTab("advisories");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Publish failed";
      alert(`Could not ingest advisory: ${msg}`);
    } finally {
      setIngestSubmitting(false);
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
              onClick={() => setShowIngestModal(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-xs font-medium text-foreground hover:border-border-strong hover:bg-surface-hover transition"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12h14" />
              </svg>
              <span>Ingest Vendor Webhook</span>
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
                No external API or dependency breaking changes have been reported. When a vendor publishes an advisory or you simulate one, Sentinel maps affected files and DataHub downstream assets.
              </p>
              <button
                onClick={() => setShowIngestModal(true)}
                className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-accent bg-accent-soft px-3.5 py-1.5 text-xs text-accent hover:opacity-90 transition"
              >
                Simulate Vendor Breaking Change
              </button>
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
                        onClick={handleScanNow}
                        className="rounded-md bg-accent px-2.5 py-1 text-xs text-white hover:opacity-90 transition"
                      >
                        Auto-Remediate
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

      {/* INGEST ADVISORY WEBHOOK MODAL */}
      {showIngestModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6">
          <div className="card w-full max-w-lg bg-surface border-border-strong p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-sm font-semibold">Publish Vendor Advisory Webhook</h3>
                <p className="text-xs text-muted">Simulate an external API provider publishing a breaking change notice.</p>
              </div>
              <button
                onClick={() => setShowIngestModal(false)}
                className="text-muted hover:text-foreground text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handlePublishAdvisory} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-muted mb-1 font-medium">Package / Vendor Name</label>
                <input
                  type="text"
                  required
                  value={ingestPkg}
                  onChange={(e) => setIngestPkg(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-foreground outline-none focus:border-accent"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-muted mb-1 font-medium">From Version</label>
                  <input
                    type="text"
                    value={ingestFrom}
                    onChange={(e) => setIngestFrom(e.target.value)}
                    className="w-full rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-foreground outline-none focus:border-accent"
                  />
                </div>
                <div>
                  <label className="block text-muted mb-1 font-medium">To (Breaking) Version</label>
                  <input
                    type="text"
                    value={ingestTo}
                    onChange={(e) => setIngestTo(e.target.value)}
                    className="w-full rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-foreground outline-none focus:border-accent"
                  />
                </div>
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Breaking Change Summary</label>
                <input
                  type="text"
                  required
                  value={ingestSummary}
                  onChange={(e) => setIngestSummary(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-foreground outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Migration Instructions</label>
                <textarea
                  rows={2}
                  value={ingestMigration}
                  onChange={(e) => setIngestMigration(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-foreground outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-muted mb-1 font-medium">Affected Symbols (comma separated)</label>
                <input
                  type="text"
                  value={ingestSymbols}
                  onChange={(e) => setIngestSymbols(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-foreground outline-none focus:border-accent"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setShowIngestModal(false)}
                  className="rounded-lg border border-border px-3.5 py-1.5 text-xs text-muted hover:text-foreground"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={ingestSubmitting}
                  className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                >
                  {ingestSubmitting ? "Publishing..." : "POST Webhook Advisory"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
