"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import ChaosSimulatorModal from "@/components/ChaosSimulatorModal";
import OnboardRepoModal from "@/components/OnboardRepoModal";
import { useAuth } from "@/lib/auth-context";

export default function LandingPage() {
  const { user } = useAuth();
  const [chaosModalOpen, setChaosModalOpen] = useState(false);
  const [onboardModalOpen, setOnboardModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"schema" | "drift" | "leakage" | "api">("schema");
  const [activeStage, setActiveStage] = useState<number>(2);

  // Live counter animation simulation with hydration safety
  const [mounted, setMounted] = useState(false);
  const [exposureAvoided, setExposureAvoided] = useState(148620);
  useEffect(() => {
    setMounted(true);
    const timer = setInterval(() => {
      setExposureAvoided((prev) => prev + Math.floor(Math.random() * 15) + 5);
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="relative min-h-screen w-full bg-[#07090D] text-foreground selection:bg-accent/30 selection:text-white font-sans overflow-x-hidden">
      {/* Dynamic Ambient Background Glows */}
      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div className="absolute -top-[20%] left-1/2 h-[700px] w-[900px] -translate-x-1/2 rounded-full bg-gradient-to-b from-accent/20 via-cyan-500/10 to-transparent blur-[140px]" />
        <div className="absolute top-[40%] -left-[10%] h-[600px] w-[600px] rounded-full bg-blue-600/10 blur-[130px]" />
        <div className="absolute top-[60%] -right-[10%] h-[600px] w-[600px] rounded-full bg-purple-600/10 blur-[140px]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#1f29370f_1px,transparent_1px),linear-gradient(to_bottom,#1f29370f_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]" />
      </div>

      {/* ========================================================================= */}
      {/* 1. TOP COMMAND BAR / NAVBAR                                               */}
      {/* ========================================================================= */}
      <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-[#07090D]/80 backdrop-blur-xl transition-all">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* Logo & Version Chip */}
          <Link href="/" className="flex items-center gap-3 group">
            <div className="relative flex h-8 w-8 items-center justify-center rounded-xl bg-accent/15 border border-accent/40 shadow-[0_0_15px_rgba(59,130,246,0.3)] group-hover:scale-105 transition">
              <span className="pulse-live absolute inline-flex h-2 w-2 rounded-full bg-accent" />
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-base font-extrabold tracking-tight text-white group-hover:text-accent transition">
                OmniSRE
              </span>
              <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[9px] font-mono font-semibold text-accent border border-accent/30">
                v2.0 AI
              </span>
            </div>
          </Link>

          {/* Navigation Links */}
          <nav className="hidden md:flex items-center gap-6 text-xs font-medium text-muted hover:text-foreground">
            <a href="#capabilities" className="hover:text-foreground transition">Capabilities</a>
            <a href="#simulator" className="hover:text-foreground transition">Chaos Simulator</a>
            <a href="#skills-registry" className="hover:text-foreground transition">Skills Registry</a>
            <a href="#architecture" className="hover:text-foreground transition">Architecture</a>
            <a href="#safety-tiers" className="hover:text-foreground transition">3-Tier Safety</a>
          </nav>

          {/* Action CTAs */}
          <div className="flex items-center gap-3">
            <Link
              href="/overview"
              className="hidden sm:inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-surface px-3.5 py-1.5 text-xs font-medium text-foreground hover:bg-surface-hover hover:border-accent/40 transition"
            >
              <span>Console Dashboard</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
              </svg>
            </Link>

            <Link
              href={user ? "/incidents" : "/login"}
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-1.5 text-xs font-bold text-white shadow-lg shadow-accent/25 hover:bg-accent/90 hover:shadow-accent/40 transition"
            >
              <span>{user ? "Open Command Center" : "Operator Sign In"}</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" x2="3" y1="12" y2="12" />
              </svg>
            </Link>
          </div>
        </div>
      </header>

      {/* ========================================================================= */}
      {/* 2. HERO SECTION                                                           */}
      {/* ========================================================================= */}
      <section className="relative z-10 mx-auto max-w-7xl px-4 pt-16 pb-20 sm:px-6 lg:px-8 text-center">
        {/* Top Eyebrow Badge */}
        <div className="inline-flex items-center gap-2 rounded-full border border-accent/30 bg-accent-soft/40 px-4 py-1.5 backdrop-blur-md shadow-[0_0_20px_rgba(59,130,246,0.15)] mb-6 animate-in fade-in slide-in-from-top-4 duration-700">
          <span className="relative flex h-2 w-2">
            <span className="pulse-live absolute inline-flex h-2 w-2 rounded-full bg-accent" />
          </span>
          <span className="text-xs font-mono font-medium text-foreground tracking-wide">
            Autonomous SRE &amp; Self-Healing Control Plane on DataHub
          </span>
        </div>

        {/* Hero Headline */}
        <h1 className="mx-auto max-w-4xl text-4xl font-extrabold tracking-tight sm:text-6xl lg:text-7xl leading-[1.08] text-white">
          Self-Healing Data &amp; ML{" "}
          <span className="bg-gradient-to-r from-blue-400 via-cyan-300 to-indigo-400 bg-clip-text text-transparent">
            at Graph Scale.
          </span>
        </h1>

        {/* Hero Subtitle */}
        <p className="mx-auto mt-6 max-w-2xl text-sm sm:text-base text-muted leading-relaxed">
          When upstream schema shifts, silent model drift, or breaking API migrations strike,{" "}
          <strong className="text-foreground font-semibold">OmniSRE</strong> traverses DataHub&apos;s
          lineage graph, diagnoses the root cause in seconds, actuates reversible Time-Machine
          mitigations, and writes verified post-mortems back into DataHub.
        </p>

        {/* Hero CTA Cluster */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3 sm:gap-4">
          <Link
            href="/incidents"
            className="flex items-center gap-2.5 rounded-xl bg-accent px-6 py-3 text-sm font-bold text-white shadow-xl shadow-accent/30 hover:bg-accent/90 hover:scale-[1.02] active:scale-[0.98] transition"
          >
            <span>⚡ Launch Command Center</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
            </svg>
          </Link>

          <button
            type="button"
            onClick={() => setChaosModalOpen(true)}
            className="flex items-center gap-2.5 rounded-xl border border-bad/40 bg-bad/10 px-6 py-3 text-sm font-bold text-bad hover:bg-bad/20 hover:border-bad/60 hover:scale-[1.02] active:scale-[0.98] shadow-lg shadow-bad/10 transition"
          >
            <span>🔥 Run Chaos Fire Drill</span>
            <span className="rounded bg-bad/30 px-1.5 py-0.2 text-[10px] font-mono font-bold">13 Scenarios</span>
          </button>

          <button
            type="button"
            onClick={() => setOnboardModalOpen(true)}
            className="flex items-center gap-2 rounded-xl border border-border bg-surface px-5 py-3 text-sm font-medium text-foreground hover:bg-surface-hover hover:border-accent/40 transition"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted">
              <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
            </svg>
            <span>+ Connect Multi-Repo</span>
          </button>
        </div>

        {/* Live Reliability Metric Ticker Strip */}
        <div className="mt-14 mx-auto max-w-5xl grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 text-left">
          <div className="rounded-2xl border border-border/80 bg-surface/70 backdrop-blur-md p-4 sm:p-5 shadow-lg">
            <span className="text-[10px] font-mono uppercase tracking-wider text-muted-dim block">Exposure Avoided</span>
            <p suppressHydrationWarning className="mt-1 text-2xl sm:text-3xl font-extrabold font-mono text-good">
              ${mounted ? exposureAvoided.toLocaleString() : "148,620"}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">Downtime financial risk averted</p>
          </div>

          <div className="rounded-2xl border border-border/80 bg-surface/70 backdrop-blur-md p-4 sm:p-5 shadow-lg">
            <span className="text-[10px] font-mono uppercase tracking-wider text-muted-dim block">Mean Time To Heal</span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold font-mono text-cyan-400">
              &lt; 8.4s
            </p>
            <p className="mt-0.5 text-[11px] text-muted">From detection to verified fix</p>
          </div>

          <div className="rounded-2xl border border-border/80 bg-surface/70 backdrop-blur-md p-4 sm:p-5 shadow-lg">
            <span className="text-[10px] font-mono uppercase tracking-wider text-muted-dim block">Chaos Drill Suite</span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold font-mono text-amber-400">
              13 Drills
            </p>
            <p className="mt-0.5 text-[11px] text-muted">Data, drift, ML &amp; code faults</p>
          </div>

          <div className="rounded-2xl border border-border/80 bg-surface/70 backdrop-blur-md p-4 sm:p-5 shadow-lg">
            <span className="text-[10px] font-mono uppercase tracking-wider text-muted-dim block">Lineage Provenance</span>
            <p className="mt-1 text-2xl sm:text-3xl font-extrabold font-mono text-accent">
              100% AST
            </p>
            <p className="mt-0.5 text-[11px] text-muted">Grounded in DataHub metadata</p>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 3. 9-STAGE CLOSED-LOOP INTERACTIVE PIPELINE ARCHITECTURE                 */}
      {/* ========================================================================= */}
      <section id="architecture" className="relative z-10 py-20 border-t border-border/60 bg-[#090C11]">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-3xl mx-auto mb-14">
            <span className="rounded-full bg-accent-soft px-3 py-1 text-[11px] font-mono text-accent border border-accent/30 uppercase tracking-wider">
              Closed-Loop Autonomy
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
              The 9-Stage Autonomous Remediation Lifecycle
            </h2>
            <p className="mt-2 text-xs sm:text-sm text-muted">
              Unlike alerting bots that dump unactionable alerts into Slack, OmniSRE executes a rigorous,
              verifiable self-healing loop over live warehouse data.
            </p>
          </div>

          {/* Stepper Buttons */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 mb-8">
            {[
              { id: 0, title: "1. Tripwire Detect", icon: "🚨", desc: "13 Assertion & Skew Probes" },
              { id: 1, title: "2. Graph Lineage", icon: "🕸️", desc: "DataHub Column Upstream" },
              { id: 2, title: "3. LLM Causality", icon: "🧠", desc: "Multi-Model Diagnosis" },
              { id: 3, title: "4. Policy Gate", icon: "🛡️", desc: "3-Tier Safety Enforcement" },
              { id: 4, title: "5. Time Machine", icon: "⏪", desc: "Reversible Journal Actuation" },
              { id: 5, title: "6. Assertion Proof", icon: "✅", desc: "Warehouse Invariant Check" },
              { id: 6, title: "7. Graph Writeback", icon: "📝", desc: "DataHub Post-Mortem Card" },
            ].map((s) => (
              <button
                key={s.id}
                onClick={() => setActiveStage(s.id)}
                className={`text-left p-3.5 rounded-xl border transition-all duration-200 ${
                  activeStage === s.id
                    ? "border-accent bg-accent-soft/30 shadow-[0_0_15px_rgba(59,130,246,0.2)] text-white"
                    : "border-border bg-surface/50 hover:bg-surface text-muted"
                }`}
              >
                <div className="flex items-center gap-1.5 text-base mb-1">
                  <span>{s.icon}</span>
                  <span className="text-xs font-bold">{s.title}</span>
                </div>
                <p className="text-[10px] text-muted-dim leading-tight">{s.desc}</p>
              </button>
            ))}
          </div>

          {/* Active Stage Deep Dive Viewport */}
          <div className="rounded-2xl border border-border-strong bg-[#05070A] p-6 sm:p-8 shadow-2xl relative overflow-hidden">
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-accent via-cyan-400 to-purple-500" />

            {activeStage === 0 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/20 text-red-400 text-lg font-bold">🚨</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 1: Multi-Detector Tripwire Engine</h3>
                      <p className="text-xs text-muted">Continuous background telemetry detecting assertion fails, distribution drift, and volume spikes.</p>
                    </div>
                  </div>
                  <span className="rounded bg-red-500/20 px-2.5 py-1 text-xs font-mono text-red-400 border border-red-500/40">TRIGGERED</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                  <div className="rounded-xl border border-border bg-surface p-4 space-y-2">
                    <span className="text-muted-dim uppercase text-[10px] block">Captured Signal Payload</span>
                    <p className="text-accent font-semibold">SIGNAL: ASSERTION_FAILED // dbt_test_not_null_raw_amount</p>
                    <p className="text-muted">Target Asset: <span className="text-white">urn:li:dataset:(duckdb,raw_transactions)</span></p>
                    <p className="text-muted">Failure: <span className="text-bad">Column &apos;amount&apos; contains 100% NULL values in partition 2026-08-11</span></p>
                  </div>
                  <div className="rounded-xl border border-border bg-surface p-4 space-y-2">
                    <span className="text-muted-dim uppercase text-[10px] block">Silent Drift Telemetry</span>
                    <p className="text-purple-400 font-semibold">DRIFT SCORE: KS-test p_val = 0.0001 (Threshold &lt; 0.05)</p>
                    <p className="text-muted">Scoring Drift: <span className="text-warn">Prediction distribution moved +2.4σ while dbt tests stayed green</span></p>
                  </div>
                </div>
              </div>
            )}

            {activeStage === 1 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/20 text-cyan-400 text-lg font-bold">🕸️</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 2: DataHub Lineage Graph Traversal</h3>
                      <p className="text-xs text-muted">Probes upstream and downstream column lineage to isolate the blast radius without guessing.</p>
                    </div>
                  </div>
                  <span className="rounded bg-cyan-500/20 px-2.5 py-1 text-xs font-mono text-cyan-400 border border-cyan-500/40">GRAPH TRAVERSED</span>
                </div>
                <div className="rounded-xl border border-border bg-surface p-4 text-xs font-mono space-y-2">
                  <p className="text-muted-dim">// Traversing OpenAPI Lineage Tree from DataHub GMS</p>
                  <p className="text-foreground"><span className="text-bad">[-] raw_transactions.amount</span> ──► <span className="text-warn">feature_store.normalized_amt</span> ──► <span className="text-purple-400">fraud_model:champion</span> ──► <span className="text-cyan-400">fraud_scoring_api</span></p>
                  <p className="text-good font-semibold">✓ Blast Radius Computed: 4 Downstream Assets Impacted • Financial Risk: $14,200/hr</p>
                </div>
              </div>
            )}

            {activeStage === 2 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-500/20 text-purple-400 text-lg font-bold">🧠</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 3: Multi-Model LLM Causal Synthesis</h3>
                      <p className="text-xs text-muted">Synthesizes evidence across code, git blame, column profiles, and historical incident memory.</p>
                    </div>
                  </div>
                  <span className="rounded bg-purple-500/20 px-2.5 py-1 text-xs font-mono text-purple-400 border border-purple-500/40">ROOT CAUSE SYNTHESIZED</span>
                </div>
                <div className="rounded-xl border border-border bg-surface p-4 text-xs font-mono space-y-2">
                  <p className="text-purple-300 font-bold">RCA Diagnosis: Upstream Schema Mutation (Confidence: 0.98)</p>
                  <p className="text-muted leading-relaxed">
                    &quot;Commit 8f3d12a renamed `amount` to `amount_cents` in the payment ingestion feed without migrating the downstream dbt transform `stg_transactions.sql`. This caused 100% missing values in downstream feature normalization.&quot;
                  </p>
                  <p className="text-accent font-medium">Memory Recall: Matched 2 prior incidents with successful remediation action `PIN_FEATURE_SNAPSHOT`.</p>
                </div>
              </div>
            )}

            {activeStage === 3 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/20 text-accent text-lg font-bold">🛡️</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 4: 3-Tier Autonomy Safety Gating</h3>
                      <p className="text-xs text-muted">Ensures destructive operations are never performed without human operator approval.</p>
                    </div>
                  </div>
                  <span className="rounded bg-accent-soft px-2.5 py-1 text-xs font-mono text-accent border border-accent/40">POLICY EVALUATED</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-mono">
                  <div className="rounded-xl border border-good/40 bg-good-soft/10 p-3 space-y-1">
                    <span className="text-good font-bold block">TIER 1: AUTO</span>
                    <p className="text-muted text-[11px]">Pin feature snapshot &amp; tag degraded assets. Executed autonomously.</p>
                  </div>
                  <div className="rounded-xl border border-warn/40 bg-warn-soft/10 p-3 space-y-1">
                    <span className="text-warn font-bold block">TIER 2: PR_ONLY</span>
                    <p className="text-muted text-[11px]">Synthesizes AST migration git diff and opens GitHub PR.</p>
                  </div>
                  <div className="rounded-xl border border-bad/40 bg-bad-soft/10 p-3 space-y-1">
                    <span className="text-bad font-bold block">TIER 3: HUMAN_ONLY</span>
                    <p className="text-muted text-[11px]">Drops tables or resets states. Enforces Slack button approval &amp; PagerDuty.</p>
                  </div>
                </div>
              </div>
            )}

            {activeStage === 4 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/20 text-amber-400 text-lg font-bold">⏪</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 5: Time-Machine Snapshot Journaling</h3>
                      <p className="text-xs text-muted">Executes containment with reversible rollback journals for every atomic operation.</p>
                    </div>
                  </div>
                  <span className="rounded bg-amber-500/20 px-2.5 py-1 text-xs font-mono text-amber-400 border border-amber-500/40">JOURNAL APPLIED</span>
                </div>
                <div className="rounded-xl border border-border bg-surface p-4 text-xs font-mono space-y-2">
                  <p className="text-good font-bold">[journal] ACTION: pin_feature(asset=&quot;training_dataset&quot;, version=&quot;2026-08-10.clean&quot;)</p>
                  <p className="text-muted">[journal] Inverse Registered: unpin_feature(asset=&quot;training_dataset&quot;)</p>
                  <p className="text-accent">[journal] Status: Clean historical partition restored. Downstream scoring unblocked.</p>
                </div>
              </div>
            )}

            {activeStage === 5 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-good/20 text-good text-lg font-bold">✅</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 6: Closed-Loop Assertion Verification</h3>
                      <p className="text-xs text-muted">Never assumes success — runs independent `@check` runners to prove warehouse health.</p>
                    </div>
                  </div>
                  <span className="rounded bg-good/20 px-2.5 py-1 text-xs font-mono text-good border border-good/40">VERIFIED GREEN</span>
                </div>
                <div className="rounded-xl border border-border bg-surface p-4 text-xs font-mono space-y-1.5">
                  <p className="text-good font-semibold">✓ Assertion 1: dbt_test_not_null_amount (Passed in 0.4s)</p>
                  <p className="text-good font-semibold">✓ Assertion 2: model_input_distribution_in_bounds (Passed in 0.6s)</p>
                  <p className="text-good font-semibold">✓ Assertion 3: fraud_scoring_api_latency_p99 &lt; 20ms (Passed in 0.2s)</p>
                  <p className="text-foreground font-bold pt-1">Result: All 3 verification gates passed with 100% confidence.</p>
                </div>
              </div>
            )}

            {activeStage === 6 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border/60 pb-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/20 text-indigo-400 text-lg font-bold">📝</span>
                    <div>
                      <h3 className="text-base font-bold text-white">Stage 7: DataHub Post-Mortem &amp; Slack Writeback</h3>
                      <p className="text-xs text-muted">Updates DataHub metadata documentation, clears degraded tags, and alerts teams.</p>
                    </div>
                  </div>
                  <span className="rounded bg-indigo-500/20 px-2.5 py-1 text-xs font-mono text-indigo-400 border border-indigo-500/40">GRAPH UPDATED</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-mono">
                  <div className="rounded-xl border border-border bg-surface p-4 space-y-2">
                    <span className="text-muted-dim uppercase text-[10px] block">DataHub MCP Writeback</span>
                    <p className="text-good">✓ Cleared tag: Sentinel-Degraded</p>
                    <p className="text-accent">✓ Wrote structured incident documentation to dataset card</p>
                    <p className="text-purple-400">✓ Updated MLflow Champion Model Registry</p>
                  </div>
                  <div className="rounded-xl border border-border bg-surface p-4 space-y-2">
                    <span className="text-muted-dim uppercase text-[10px] block">Slack &amp; Business ROI</span>
                    <p className="text-foreground font-bold">📢 Posted Block Kit card to #all-prodml</p>
                    <p className="text-good font-bold">💰 Downtime Exposure Avoided: $14,200</p>
                    <p className="text-muted">⏱️ MTTR: 7.8 seconds</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 4. CHAOS SCENARIOS SHOWCASE                                              */}
      {/* ========================================================================= */}
      <section id="simulator" className="relative z-10 py-20 border-t border-border/60 bg-[#07090D]">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-12">
            <div>
              <span className="rounded-full bg-bad/20 px-3 py-1 text-[11px] font-mono text-bad border border-bad/30 uppercase tracking-wider">
                Production Chaos Suite
              </span>
              <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
                13 Battle-Tested Fire Drills
              </h2>
              <p className="mt-2 text-xs sm:text-sm text-muted">
                Experience how OmniSRE heals real data quality, silent model decay, and dependency regressions.
              </p>
            </div>

            <button
              onClick={() => setChaosModalOpen(true)}
              className="inline-flex items-center gap-2 rounded-xl bg-bad hover:bg-bad/90 px-5 py-2.5 text-xs font-bold text-white shadow-lg shadow-bad/20 transition self-start md:self-auto"
            >
              <span>⚡ Open Live Chaos Simulator</span>
            </button>
          </div>

          {/* Scenario Tabs */}
          <div className="flex flex-wrap gap-2 border-b border-border/80 pb-4 mb-8">
            {[
              { id: "schema", label: "Schema Change", icon: "📐", cat: "Data Quality" },
              { id: "drift", label: "Distribution Drift", icon: "📈", cat: "Silent Model Failure" },
              { id: "leakage", label: "Label Leakage (100% ROC)", icon: "🎯", cat: "ML Overfitting" },
              { id: "api", label: "API Breaking Change", icon: "📦", cat: "Supply Chain / Code" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as typeof activeTab)}
                className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition ${
                  activeTab === tab.id
                    ? "bg-surface-raised border border-accent text-white shadow-md"
                    : "bg-surface/40 border border-border text-muted hover:text-foreground"
                }`}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                <span className="text-[10px] font-mono text-muted-dim">({tab.cat})</span>
              </button>
            ))}
          </div>

          {/* Active Scenario Card Showcase */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-7 rounded-2xl border border-border bg-[#05070A] p-6 text-xs font-mono space-y-4 shadow-xl">
              <div className="flex items-center justify-between border-b border-border pb-3">
                <span className="text-muted-dim">TERMINAL // omnisre-agent --drill</span>
                <span className="rounded bg-accent-soft px-2 py-0.5 text-[10px] text-accent">STATUS: SOLVED IN 8.1s</span>
              </div>

              {activeTab === "schema" && (
                <div className="space-y-3 leading-relaxed">
                  <p className="text-bad">[fault_inject] Upstream DB dropped column &apos;amount&apos; -&gt; renamed to &apos;amount_cents&apos;</p>
                  <p className="text-cyan-400">[detect] DataHub assertion &apos;raw_transactions.not_null_amount&apos; FAILED</p>
                  <p className="text-purple-400">[lineage] Traversed 4 downstream models to feature_store &amp; fraud_scoring_api</p>
                  <p className="text-amber-400">[policy] Evaluated Tier 1 AUTO: Pinning clean historical snapshot</p>
                  <p className="text-good font-bold">[validate] 3 warehouse assertions PASSED. Pipeline restored without downtime.</p>
                </div>
              )}

              {activeTab === "drift" && (
                <div className="space-y-3 leading-relaxed">
                  <p className="text-warn">[fault_inject] Uniform 2.2x price shift introduced. All 22 dbt assertions stay GREEN.</p>
                  <p className="text-cyan-400">[detect] OmniSRE Silent Drift Detector flagged prediction distribution anomaly</p>
                  <p className="text-purple-400">[rca] Kolmogorov-Smirnov test p_val = 0.0001 over transaction features</p>
                  <p className="text-amber-400">[actuate] Repointed MLflow alias &apos;champion&apos; to robust fallback model</p>
                  <p className="text-good font-bold">[validate] Scoring accuracy back to 96.4%. Incident closed.</p>
                </div>
              )}

              {activeTab === "leakage" && (
                <div className="space-y-3 leading-relaxed">
                  <p className="text-bad">[fault_inject] Post-hoc surcharge column leaked into training dataset</p>
                  <p className="text-cyan-400">[detect] Suspicious model evaluation ROC-AUC spiked to 0.999</p>
                  <p className="text-purple-400">[rca] Feature importance probe isolated &apos;surcharge_applied&apos; (weight: 0.94)</p>
                  <p className="text-amber-400">[actuate] Blocked model promotion &amp; synthesized feature exclusion diff</p>
                  <p className="text-good font-bold">[validate] Model retrained with clean features. Promotion unblocked.</p>
                </div>
              )}

              {activeTab === "api" && (
                <div className="space-y-3 leading-relaxed">
                  <p className="text-bad">[fault_inject] Vendor released breaking parameter change in scikit-learn 1.6</p>
                  <p className="text-cyan-400">[detect] Registry monitor matched advisory CVE-2026-BREAK against codebase AST</p>
                  <p className="text-purple-400">[llm_diff] Synthesized backward-compatible migration PR diff</p>
                  <p className="text-amber-400">[git] Opened GitHub Pull Request with automated test suite</p>
                  <p className="text-good font-bold">[validate] Self-maintaining API migration complete.</p>
                </div>
              )}
            </div>

            <div className="lg:col-span-5 rounded-2xl border border-border bg-surface/70 p-6 flex flex-col justify-between shadow-xl">
              <div>
                <span className="text-[10px] font-mono uppercase text-muted-dim block">Business Impact Analysis</span>
                <h3 className="mt-1 text-lg font-bold text-white">Why Conventional Alerting Fails</h3>
                <p className="mt-2 text-xs text-muted leading-relaxed">
                  Traditional monitoring stops at alerting an on-call engineer on Slack. OmniSRE takes action:
                  quarantining bad partitions, freezing clean feature snapshots, and keeping customer ML predictions live.
                </p>
              </div>

              <div className="mt-6 border-t border-border pt-4 space-y-3">
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-muted">Human Triage Time:</span>
                  <span className="text-bad line-through">45 - 90 mins</span>
                </div>
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-muted">OmniSRE Autonomous MTTR:</span>
                  <span className="text-good font-bold">&lt; 10 seconds</span>
                </div>
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-muted">Financial ROI Avoided:</span>
                  <span className="text-accent font-bold">$12,000 - $48,000 / drill</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 5. DATAHUB SKILLS REGISTRY & PLUGIN SYSTEM                                */}
      {/* ========================================================================= */}
      <section id="skills-registry" className="relative z-10 py-20 border-t border-border/60 bg-[#090C11]">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-3xl mx-auto mb-14">
            <span className="rounded-full bg-cyan-500/20 px-3 py-1 text-[11px] font-mono text-cyan-400 border border-cyan-500/30 uppercase tracking-wider">
              Open Plugin Architecture
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
              Extensible DataHub Skills Registry
            </h2>
            <p className="mt-2 text-xs sm:text-sm text-muted">
              Add new domain-specific detectors, causal probes, and reversible actuators in 5 lines of Python.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
            {/* Skills 4 Pillars */}
            <div className="lg:col-span-5 space-y-3.5">
              <div className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-center gap-2 font-mono text-xs font-bold text-accent">
                  <span>@detector</span>
                  <span className="text-[10px] text-muted font-normal">• How do we notice?</span>
                </div>
                <p className="mt-1 text-xs text-muted">Assertion anomalies, volume collapse, prediction drift, and git commit triggers.</p>
              </div>

              <div className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-center gap-2 font-mono text-xs font-bold text-purple-400">
                  <span>@probe</span>
                  <span className="text-[10px] text-muted font-normal">• What grounded evidence explains it?</span>
                </div>
                <p className="mt-1 text-xs text-muted">Column lineage traversal, profile statistical tests, git blame, and package AST scanning.</p>
              </div>

              <div className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-center gap-2 font-mono text-xs font-bold text-amber-400">
                  <span>@actuator</span>
                  <span className="text-[10px] text-muted font-normal">• How do we fix it reversibly?</span>
                </div>
                <p className="mt-1 text-xs text-muted">Pin feature snapshot, quarantine partition, tag degraded, repoint MLflow alias.</p>
              </div>

              <div className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-center gap-2 font-mono text-xs font-bold text-good">
                  <span>@check</span>
                  <span className="text-[10px] text-muted font-normal">• How do we prove the fix worked?</span>
                </div>
                <p className="mt-1 text-xs text-muted">Warehouse invariants, dbt verification assertions, and ML serving latency checks.</p>
              </div>
            </div>

            {/* Code Snippet Card */}
            <div className="lg:col-span-7 rounded-2xl border border-border-strong bg-[#05070A] p-6 shadow-2xl font-mono text-xs text-foreground/90 overflow-hidden">
              <div className="flex items-center justify-between pb-3 border-b border-border/80 text-muted-dim text-[11px]">
                <span>agent/tools/probes/custom_distribution.py</span>
                <span className="text-cyan-400">Python 3.11</span>
              </div>
              <pre className="mt-4 overflow-x-auto text-[11px] leading-relaxed text-gray-300">
                <code>
{`from agent.registry import probe
from agent.contracts import Evidence, Incident

@probe
class CustomDistributionProbe:
    """Diagnostic skill inspecting DataHub column statistical drift."""
    
    def __init__(self, gms_server: str = "http://localhost:8080"):
        self.gms = gms_server

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type == "distribution_drift"

    def investigate(self, incident: Incident) -> list[Evidence]:
        # Perform graph traversal & statistical tests over DataHub metadata
        return [
            Evidence(name="ks_test", value={"p_value": 0.0001, "drift": True})
        ]`}
                </code>
              </pre>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 6. 3-TIER SAFETY & SLACK BLOCK KIT SHOWCASE                               */}
      {/* ========================================================================= */}
      <section id="safety-tiers" className="relative z-10 py-20 border-t border-border/60 bg-[#07090D]">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-3xl mx-auto mb-14">
            <span className="rounded-full bg-purple-500/20 px-3 py-1 text-[11px] font-mono text-purple-400 border border-purple-500/30 uppercase tracking-wider">
              Human-In-The-Loop Safety
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
              Enterprise 3-Tier Safety &amp; Alerting
            </h2>
            <p className="mt-2 text-xs sm:text-sm text-muted">
              Zero black-box actions. Dangerous operations enforce Slack button approvals and PagerDuty escalations.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-center">
            {/* Slack Mockup Card */}
            <div className="rounded-2xl border border-border bg-[#1A1D21] p-6 shadow-2xl text-white font-sans text-xs space-y-4">
              <div className="flex items-center justify-between border-b border-white/10 pb-3">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm">#all-prodml</span>
                  <span className="rounded bg-white/10 px-2 py-0.5 text-[10px] text-muted">SLACK BOT</span>
                </div>
                <span className="text-[10px] text-muted font-mono">Just now</span>
              </div>

              <div className="flex items-start gap-3 bg-[#222529] p-4 rounded-xl border border-white/10">
                <span className="text-xl">🚨</span>
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center justify-between">
                    <p className="font-bold text-sm text-white">[HIGH] Schema Anomaly Detected</p>
                    <span className="rounded bg-accent/20 px-2 py-0.5 text-[10px] font-mono text-accent">Confidence: 0.98</span>
                  </div>
                  <p className="text-gray-300 text-xs">Repository: <span className="font-bold text-white">SRINJOY59/Datahub-Hackathon</span></p>
                  <p className="text-gray-400 text-xs">Root Cause: Column &apos;amount&apos; renamed to &apos;amount_cents&apos; in payment ingestion feed.</p>
                  <p className="text-good font-semibold text-xs">Action Proposed: Pin feature snapshot to last-good partition 2026-08-10.</p>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <button type="button" className="rounded-lg bg-good hover:bg-good/90 px-4 py-2 text-xs font-bold text-white shadow">
                  Approve Remediation (Enter)
                </button>
                <button type="button" className="rounded-lg bg-white/10 hover:bg-white/20 px-4 py-2 text-xs font-medium text-gray-300">
                  Reject &amp; Escalate (P)
                </button>
              </div>
            </div>

            {/* Safety Tier Cards */}
            <div className="space-y-4">
              <div className="rounded-xl border border-good/40 bg-good-soft/10 p-5 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-bold text-good text-sm">TIER 1: AUTO-RESOLVE</h4>
                  <span className="rounded bg-good/20 px-2 py-0.5 text-[10px] font-mono text-good">Autonomous</span>
                </div>
                <p className="text-xs text-muted leading-relaxed">
                  Protective, non-destructive actions such as tagging degraded datasets in DataHub, pausing downstream batch consumers, or pin-pointing clean historical snapshots.
                </p>
              </div>

              <div className="rounded-xl border border-warn/40 bg-warn-soft/10 p-5 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-bold text-warn text-sm">TIER 2: PR_ONLY</h4>
                  <span className="rounded bg-warn/20 px-2 py-0.5 text-[10px] font-mono text-warn">GitHub Review</span>
                </div>
                <p className="text-xs text-muted leading-relaxed">
                  Code changes, model retraining triggers, and dbt schema updates generate a detailed GitHub Pull Request with AST diffs and test results.
                </p>
              </div>

              <div className="rounded-xl border border-bad/40 bg-bad-soft/10 p-5 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-bold text-bad text-sm">TIER 3: HUMAN_ONLY</h4>
                  <span className="rounded bg-bad/20 px-2 py-0.5 text-[10px] font-mono text-bad">PagerDuty + Slack</span>
                </div>
                <p className="text-xs text-muted leading-relaxed">
                  Destructive mutations (e.g. database schema alterations or partition drops) pause for human sign-off via Slack interactive buttons and page the on-call engineer.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 7. BOTTOM CALL TO ACTION                                                  */}
      {/* ========================================================================= */}
      <section className="relative z-10 py-20 border-t border-border/60 bg-gradient-to-b from-[#07090D] via-surface/40 to-[#07090D] text-center">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 space-y-6">
          <h2 className="text-3xl sm:text-5xl font-black text-white tracking-tight">
            Stop being a human circuit breaker.
          </h2>
          <p className="text-sm sm:text-base text-muted max-w-2xl mx-auto leading-relaxed">
            Deploy OmniSRE to eliminate 3 AM incident fire drills and run autonomous, self-healing data and ML pipelines.
          </p>

          <div className="pt-4 flex flex-wrap items-center justify-center gap-4">
            <Link
              href="/incidents"
              className="flex items-center gap-2 rounded-xl bg-accent px-8 py-3.5 text-sm font-bold text-white shadow-2xl shadow-accent/40 hover:bg-accent/90 hover:scale-105 transition"
            >
              <span>⚡ Enter Incident Command Center</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
              </svg>
            </Link>

            <button
              onClick={() => setChaosModalOpen(true)}
              className="flex items-center gap-2 rounded-xl border border-bad/40 bg-bad/10 px-7 py-3.5 text-sm font-bold text-bad hover:bg-bad/20 transition"
            >
              <span>🔥 Launch Fire Drill Demo</span>
            </button>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 8. FOOTER                                                                 */}
      {/* ========================================================================= */}
      <footer className="border-t border-border/40 bg-[#05070A] py-8 text-xs text-muted">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-white">OmniSRE</span>
            <span>• Multi-Repo Self-Healing Data &amp; ML Governance Platform on DataHub</span>
          </div>
          <div className="flex items-center gap-6">
            <Link href="/overview" className="hover:text-foreground transition">Overview</Link>
            <Link href="/incidents" className="hover:text-foreground transition">Incidents</Link>
            <Link href="/pipeline" className="hover:text-foreground transition">Pipeline</Link>
            <Link href="/chat" className="hover:text-foreground transition">Ask On-Call</Link>
            <a href="https://github.com/SRINJOY59/Datahub-Hackathon" target="_blank" rel="noreferrer" className="hover:text-foreground transition">
              GitHub Repo
            </a>
          </div>
        </div>
      </footer>

      {/* Modals */}
      <ChaosSimulatorModal
        open={chaosModalOpen}
        onClose={() => setChaosModalOpen(false)}
      />
      <OnboardRepoModal
        open={onboardModalOpen}
        onClose={() => setOnboardModalOpen(false)}
        onSuccess={() => {
          window.location.reload();
        }}
      />
    </div>
  );
}
