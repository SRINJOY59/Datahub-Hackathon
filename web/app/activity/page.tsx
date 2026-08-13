"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchJournal, fetchWebhookActivity } from "@/lib/queries";
import type { JournalEntry, WebhookActivity } from "@/lib/types";
import {
  fetchActionsConfig, fetchJobs, runDrill, runRollback,
  type ActionsConfig, type Job,
} from "@/lib/actions";

const POLL_MS = 6_000;

const STATUS_TONE: Record<string, string> = {
  applied: "text-good bg-good-soft",
  reverted: "text-warn bg-warn-soft",
  failed: "text-bad bg-bad-soft",
  simulated: "text-muted bg-surface-raised",
};

export default function ActivityPage() {
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookActivity | null>(null);
  const [config, setConfig] = useState<ActionsConfig | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [scenario, setScenario] = useState("");
  const [rollbackId, setRollbackId] = useState("");
  const [confirming, setConfirming] = useState<null | "drill" | "rollback">(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    fetchActionsConfig()
      .then((c) => {
        setConfig(c);
        if (c.scenarios.length) setScenario(c.scenarios[0]);
      })
      .catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([fetchJournal(60), fetchWebhookActivity(), fetchJobs()])
        .then(([j, w, jb]) => {
          if (cancelled) return;
          setJournal(j);
          setWebhooks(w);
          setJobs(jb);
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  async function fire(kind: "drill" | "rollback") {
    setActionError(null);
    setConfirming(null);
    try {
      const job = kind === "drill" ? await runDrill(scenario) : await runRollback(rollbackId);
      setJobs((prev) => [job, ...prev]);
    } catch (e) {
      setActionError(String(e instanceof Error ? e.message : e));
    }
  }

  return (
    <div className="px-4 py-5 space-y-6 sm:px-6 md:px-8 md:py-7 md:space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Activity</h1>
        <p className="mt-1 text-sm text-muted">
          Every action the agent has taken, the webhooks that triggered it, and
          the controls to drive it manually.
        </p>
      </div>

      {config?.enabled && (
        <section className="card p-5">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-sm font-medium">Controls</h2>
              <p className="mt-1 text-xs text-muted">
                These write to the real pipeline. There is no authentication on
                this endpoint — see{" "}
                <code className="text-[11px]">config/dashboard.yaml</code>.
              </p>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            {config.allowDrill && (
              <div className="rounded-lg border border-border p-4">
                <p className="text-sm font-medium">Fire drill</p>
                <p className="mt-1 text-xs text-muted">
                  Breaks the pipeline on purpose, then lets the agent heal it.
                </p>
                <div className="mt-3 flex gap-2">
                  <select
                    value={scenario}
                    onChange={(e) => setScenario(e.target.value)}
                    className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-xs outline-none focus:border-accent"
                  >
                    {config.scenarios.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                  <button
                    onClick={() => setConfirming("drill")}
                    className="rounded-md border border-warn/40 bg-warn-soft px-3 py-1.5 text-xs text-warn"
                  >
                    Run
                  </button>
                </div>
                {confirming === "drill" && (
                  <Confirm
                    text={`Inject "${scenario}" into the live pipeline?`}
                    onConfirm={() => fire("drill")}
                    onCancel={() => setConfirming(null)}
                  />
                )}
              </div>
            )}

            {config.allowRollback && (
              <div className="rounded-lg border border-border p-4">
                <p className="text-sm font-medium">Roll back an incident</p>
                <p className="mt-1 text-xs text-muted">
                  Withdraws every action for an incident through the journal.
                </p>
                <div className="mt-3 flex gap-2">
                  <input
                    value={rollbackId}
                    onChange={(e) => setRollbackId(e.target.value)}
                    placeholder="INC-1234"
                    className="flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-xs outline-none focus:border-accent"
                  />
                  <button
                    onClick={() => setConfirming("rollback")}
                    disabled={!rollbackId.trim()}
                    className="rounded-md border border-bad/40 bg-bad-soft px-3 py-1.5 text-xs text-bad disabled:opacity-40"
                  >
                    Undo
                  </button>
                </div>
                {confirming === "rollback" && (
                  <Confirm
                    text={`Withdraw every applied action for ${rollbackId}?`}
                    onConfirm={() => fire("rollback")}
                    onCancel={() => setConfirming(null)}
                  />
                )}
              </div>
            )}
          </div>

          {actionError && (
            <p className="mt-3 rounded-md bg-bad-soft p-2 text-xs text-bad">{actionError}</p>
          )}

          {jobs.length > 0 && (
            <div className="mt-4 border-t border-border pt-4">
              <h3 className="text-xs font-medium text-muted">Recent jobs</h3>
              <ul className="mt-2 space-y-2">
                {jobs.slice(0, 5).map((j) => (
                  <li key={j.id} className="rounded-md bg-surface-raised p-2.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span>
                        <span className="font-medium">{j.kind}</span>{" "}
                        <span className="text-muted">{j.target}</span>
                      </span>
                      <span
                        className={
                          j.status === "succeeded" ? "text-good"
                            : j.status === "failed" ? "text-bad" : "text-warn"
                        }
                      >
                        {j.status}
                      </span>
                    </div>
                    {j.error && <p className="mt-1 text-bad">{j.error}</p>}
                    {j.log.length > 0 && (
                      <ul className="mt-1 font-mono text-[11px] text-muted">
                        {j.log.map((l, i) => <li key={i}>{l}</li>)}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <h2 className="text-sm font-medium">Action journal</h2>
          <p className="mt-1 text-xs text-muted">
            Append-only audit trail — every action with its reversibility.
          </p>
          <div className="mt-4 max-h-[520px] space-y-2 overflow-y-auto scrollbar-thin">
            {journal.length === 0 && (
              <p className="py-8 text-center text-sm text-muted">Nothing recorded yet.</p>
            )}
            {journal.map((e, i) => (
              <div key={i} className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    {e.actionType.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[11px] ${
                      STATUS_TONE[e.status] ?? "text-muted bg-surface-raised"
                    }`}
                  >
                    {e.status}
                  </span>
                  {e.incidentId && (
                    <Link
                      href={`/incidents/${e.incidentId}`}
                      className="font-mono text-[11px] text-accent hover:underline"
                    >
                      {e.incidentId}
                    </Link>
                  )}
                  {e.reversible && (
                    <span className="text-[11px] text-muted">reversible</span>
                  )}
                </div>
                <p className="mt-1 truncate font-mono text-[11px] text-muted" title={e.target}>
                  {e.target}
                </p>
                {e.note && <p className="mt-1 text-xs text-muted">{e.note}</p>}
              </div>
            ))}
          </div>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-medium">Webhook activity</h2>
          {webhooks && !webhooks.attached ? (
            <p className="mt-3 text-xs text-muted">
              The webhook queue isn&apos;t attached — this API is running
              standalone. Start it with <code>python -m agent serve</code> to see
              live deliveries.
            </p>
          ) : (
            <>
              <p className="mt-1 text-xs text-muted">
                {webhooks?.active.length ?? 0} running ·{" "}
                {webhooks?.recent.length ?? 0} recent
              </p>
              <div className="mt-4 space-y-2">
                {[...(webhooks?.active ?? []), ...(webhooks?.recent ?? [])].length === 0 && (
                  <p className="py-6 text-center text-xs text-muted">
                    No deliveries yet.
                  </p>
                )}
                {[...(webhooks?.active ?? []), ...(webhooks?.recent ?? [])].map((r) => (
                  <div key={r.runId} className="rounded-md border border-border p-2.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{r.source}</span>
                      <span
                        className={
                          r.status === "completed" ? "text-good"
                            : r.status === "failed" ? "text-bad" : "text-warn"
                        }
                      >
                        {r.status}
                      </span>
                    </div>
                    <p className="mt-1 truncate font-mono text-[10px] text-muted">
                      {r.assetUrn}
                    </p>
                    {r.error && <p className="mt-1 text-bad">{r.error}</p>}
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function Confirm({
  text, onConfirm, onCancel,
}: { text: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="mt-3 rounded-md border border-warn/40 bg-warn-soft p-3">
      <p className="text-xs text-warn">{text}</p>
      <div className="mt-2 flex gap-2">
        <button
          onClick={onConfirm}
          className="rounded-md bg-warn px-3 py-1 text-xs font-medium text-black"
        >
          Confirm
        </button>
        <button onClick={onCancel} className="rounded-md border border-border px-3 py-1 text-xs">
          Cancel
        </button>
      </div>
    </div>
  );
}
