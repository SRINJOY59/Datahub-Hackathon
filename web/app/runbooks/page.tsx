"use client";

import { useEffect, useState } from "react";
import { fetchRunbooks } from "@/lib/queries";
import type { Runbook } from "@/lib/types";

export default function RunbooksPage() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchRunbooks()
      .then((r) => {
        setRunbooks(r);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const registered = runbooks.filter((r) => r.registered);
  const pending = runbooks.filter((r) => !r.registered);

  return (
    <div className="px-8 py-7 max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Runbooks</h1>
        <p className="mt-1 text-sm text-muted">
          Procedures synthesised from resolved incidents and registered in DataHub
          as <code className="text-xs">AgentSkill</code> entities — the agent&apos;s
          accumulated knowledge, readable by other agents.
        </p>
      </div>

      {error && (
        <div className="card border-bad/40 bg-bad-soft p-4 text-sm text-bad">
          Can&apos;t load runbooks — is DataHub reachable?
        </div>
      )}

      {loading && <p className="py-12 text-center text-sm text-muted">Loading…</p>}

      {!loading && runbooks.length === 0 && !error && (
        <p className="py-12 text-center text-sm text-muted">
          No post-mortem history yet — resolve some incidents first.
        </p>
      )}

      {registered.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted">Registered</h2>
          {registered.map((r) => (
            <div key={r.changeType} className="card p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="font-medium">{r.title ?? r.changeType}</p>
                  <p className="mt-1 text-sm text-muted">{r.description}</p>
                </div>
                <span className="shrink-0 rounded-full bg-good-soft px-2.5 py-0.5 text-xs text-good">
                  registered
                </span>
              </div>
              <p className="mt-3 font-mono text-[10px] text-muted">{r.skillUrn}</p>
              {r.instructions && (
                <>
                  <button
                    onClick={() => setOpen(open === r.changeType ? null : r.changeType)}
                    className="mt-3 text-xs text-accent hover:underline"
                  >
                    {open === r.changeType ? "Hide" : "Show"} instructions
                  </button>
                  {open === r.changeType && (
                    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-surface-raised p-3 text-xs text-muted scrollbar-thin">
                      {r.instructions}
                    </pre>
                  )}
                </>
              )}
            </div>
          ))}
        </section>
      )}

      {pending.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted">
            Eligible — not yet synthesised
          </h2>
          <p className="text-xs text-muted">
            Run <code>python -m agent runbooks</code> to generate and register these.
          </p>
          <div className="card divide-y divide-border">
            {pending.map((r) => (
              <div
                key={r.changeType}
                className="flex items-center justify-between px-5 py-3"
              >
                <span className="text-sm">{r.changeType.replace(/_/g, " ")}</span>
                <span className="text-xs text-muted">
                  {r.incidentsBacking} post-mortem
                  {r.incidentsBacking === 1 ? "" : "s"}
                  {r.incidentsNeeded > 0
                    ? ` · needs ${r.incidentsNeeded} more`
                    : " · ready"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
