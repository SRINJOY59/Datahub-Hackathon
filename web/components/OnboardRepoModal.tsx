"use client";

import { useState } from "react";
import Link from "next/link";
import { onboardRepository } from "@/lib/queries";
import type { OnboardedRepoResult } from "@/lib/types";

interface OnboardRepoModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (result: OnboardedRepoResult) => void;
}

export default function OnboardRepoModal({ open, onClose, onSuccess }: OnboardRepoModalProps) {
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [stage, setStage] = useState<"idle" | "scanning" | "emitting" | "completed" | "error">("idle");
  const [result, setResult] = useState<OnboardedRepoResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleFinishAndReload = () => {
    onClose();
    if (result) {
      window.dispatchEvent(new CustomEvent("sentinel:repo-switched", { detail: { repoId: result.repoName } }));
    }
    window.location.reload();
  };

  const handleModalClose = () => {
    if (stage === "completed") {
      handleFinishAndReload();
    } else {
      onClose();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setStage("scanning");

    try {
      await new Promise((r) => setTimeout(r, 600));
      setStage("emitting");

      const res = await onboardRepository(repoUrl.trim(), branch);
      await new Promise((r) => setTimeout(r, 600));

      setResult(res);
      setStage("completed");
      if (onSuccess) onSuccess(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to onboard repository";
      setError(msg);
      setStage("error");
    }
  };

  return (
    <div
      style={{ zIndex: 9999 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
    >
      <div className="card w-full max-w-2xl bg-surface border-border-strong p-6 space-y-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border pb-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/20 text-accent font-bold text-sm">
              +
            </span>
            <div>
              <h2 className="text-base font-semibold">Connect Repository & Bootstrap DataHub</h2>
              <p className="text-xs text-muted">
                Auto-discover ML pipelines, emit full DataHub lineage, and link MLflow experiments.
              </p>
            </div>
          </div>
          <button
            onClick={handleModalClose}
            className="rounded-md p-1.5 text-muted hover:bg-surface-raised hover:text-foreground"
          >
            ✕
          </button>
        </div>

        {/* Input Form */}
        {stage === "idle" && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted uppercase tracking-wider mb-1.5">
                GitHub Repository URL or Local Path
              </label>
              <input
                type="text"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/org/fraud-pipeline or leave blank for workspace"
                className="w-full rounded-lg border border-border bg-surface-raised px-3.5 py-2 text-xs font-mono text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-[11px] text-muted">
                Leave empty to automatically scan and bootstrap this active workspace repository.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-muted uppercase tracking-wider mb-1.5">
                  Default Branch
                </label>
                <input
                  type="text"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-raised px-3.5 py-2 text-xs text-foreground focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted uppercase tracking-wider mb-1.5">
                  Target DataHub Platform
                </label>
                <input
                  type="text"
                  readOnly
                  value="DataHub GMS + MLflow"
                  className="w-full rounded-lg border border-border bg-surface-raised/50 px-3.5 py-2 text-xs text-muted cursor-not-allowed"
                />
              </div>
            </div>

            <div className="rounded-lg border border-accent/30 bg-accent-soft/20 p-3.5 text-xs text-muted space-y-1">
              <p className="font-medium text-foreground">What OmniSRE does automatically:</p>
              <ul className="list-disc list-inside space-y-0.5 text-[11px]">
                <li>Scans Python AST for ML models (<code className="text-accent">sklearn</code>, <code className="text-accent">torch</code>, <code className="text-accent">xgboost</code>) & data sources.</li>
                <li>Emits Dataset, DataJob, and MLModel lineage directly to DataHub without manual YAML recipes.</li>
                <li>Initializes a dedicated MLflow tracking experiment namespace.</li>
              </ul>
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-border px-4 py-2 text-xs font-medium text-muted hover:text-foreground"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-accent px-5 py-2 text-xs font-medium text-white shadow-md hover:opacity-90 transition"
              >
                Analyze & Bootstrap Lineage →
              </button>
            </div>
          </form>
        )}

        {/* In-Flight HUD */}
        {(stage === "scanning" || stage === "emitting") && (
          <div className="py-6 space-y-4 text-center">
            <div className="mx-auto h-10 w-10 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            <div>
              <p className="font-medium text-sm">
                {stage === "scanning"
                  ? "Scanning Codebase AST & Extracting Datasets..."
                  : "Emitting Full Lineage Graph to DataHub GMS & MLflow..."}
              </p>
              <p className="text-xs text-muted mt-1">
                Parsing models, SQL transformations, and constructing lineage nodes...
              </p>
            </div>
          </div>
        )}

        {/* Completed View */}
        {stage === "completed" && result && (
          <div className="space-y-4">
            <div className="rounded-lg border border-good/40 bg-good-soft/20 p-3.5 text-xs">
              <p className="font-semibold text-good">
                ✓ Repository Onboarded Successfully ({result.repoName})
              </p>
              <p className="text-[11px] text-muted mt-0.5">
                DataHub lineage graph has been emitted and MLflow experiment namespace is active.
              </p>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-4 gap-2 text-center">
              <div className="rounded-lg border border-border bg-surface-raised p-2.5">
                <span className="block text-lg font-bold text-foreground">{result.datasetsCount}</span>
                <span className="text-[10px] text-muted uppercase">Datasets</span>
              </div>
              <div className="rounded-lg border border-border bg-surface-raised p-2.5">
                <span className="block text-lg font-bold text-foreground">{result.modelsCount}</span>
                <span className="text-[10px] text-muted uppercase">ML Models</span>
              </div>
              <div className="rounded-lg border border-border bg-surface-raised p-2.5">
                <span className="block text-lg font-bold text-foreground">{result.jobsCount}</span>
                <span className="text-[10px] text-muted uppercase">Data Jobs</span>
              </div>
              <div className="rounded-lg border border-border bg-surface-raised p-2.5">
                <span className="block text-lg font-bold text-good">{result.lineageEdgesCount}</span>
                <span className="text-[10px] text-muted uppercase">Lineage Edges</span>
              </div>
            </div>

            {/* Discovered Lineage Nodes */}
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted uppercase tracking-wider">Discovered Entities</p>
              <div className="max-h-36 overflow-y-auto space-y-1.5 scrollbar-thin border border-border rounded-lg p-2 bg-surface-raised/40">
                {result.entities.map((ent, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs font-mono p-1 rounded bg-surface border border-border/40">
                    <div className="flex items-center gap-2 truncate">
                      <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[10px] text-accent uppercase">
                        {ent.kind}
                      </span>
                      <span className="truncate">{ent.name}</span>
                    </div>
                    <span className="text-[11px] text-muted truncate">{ent.file}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick Actions */}
            <div className="grid grid-cols-3 gap-2.5 pt-1">
              <Link
                href="/pipeline"
                onClick={handleFinishAndReload}
                className="rounded-lg border border-border bg-surface-raised p-2.5 text-center text-xs hover:border-accent/60 transition group"
              >
                <span className="block text-sm mb-1 group-hover:scale-110 transition">🌐</span>
                <span className="font-semibold text-foreground text-[11px] block">Pipeline Lineage</span>
                <span className="text-[10px] text-muted">View DAG & nodes</span>
              </Link>
              <Link
                href="/api-health"
                onClick={handleFinishAndReload}
                className="rounded-lg border border-border bg-surface-raised p-2.5 text-center text-xs hover:border-accent/60 transition group"
              >
                <span className="block text-sm mb-1 group-hover:scale-110 transition">🛡️</span>
                <span className="font-semibold text-foreground text-[11px] block">API Health</span>
                <span className="text-[10px] text-muted">Scan vulnerabilities</span>
              </Link>
              <Link
                href="/incidents"
                onClick={handleFinishAndReload}
                className="rounded-lg border border-border bg-surface-raised p-2.5 text-center text-xs hover:border-accent/60 transition group"
              >
                <span className="block text-sm mb-1 group-hover:scale-110 transition">⚡</span>
                <span className="font-semibold text-foreground text-[11px] block">Chaos & SRE</span>
                <span className="text-[10px] text-muted">Run self-healing drills</span>
              </Link>
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-2.5 pt-2 border-t border-border">
              <button
                onClick={handleFinishAndReload}
                className="rounded-lg bg-accent px-5 py-2 text-xs font-medium text-white hover:opacity-90 transition"
              >
                Explore Active Repository →
              </button>
            </div>
          </div>
        )}

        {/* Error View */}
        {stage === "error" && (
          <div className="space-y-4">
            <div className="rounded-lg border border-bad/40 bg-bad-soft/30 p-3.5 text-xs text-bad">
              <p className="font-semibold">Onboarding Failed</p>
              <p className="text-[11px] mt-0.5">{error}</p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setStage("idle")}
                className="rounded-lg border border-border px-4 py-2 text-xs font-medium text-muted hover:text-foreground"
              >
                Try Again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
