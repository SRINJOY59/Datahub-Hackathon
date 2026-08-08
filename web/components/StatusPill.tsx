"use client";

import { useEffect, useState } from "react";
import { fetchSystemStatus } from "@/lib/queries";
import type { SystemStatus } from "@/lib/types";

const POLL_MS = 15_000;

export default function StatusPill() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchSystemStatus()
        .then((s) => {
          if (!cancelled) {
            setStatus(s);
            setError(false);
          }
        })
        .catch(() => !cancelled && setError(true));
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-bad-soft px-2.5 py-2 text-xs text-bad">
        <span className="h-1.5 w-1.5 rounded-full bg-bad" />
        backend offline
      </div>
    );
  }

  if (!status) {
    return <div className="skeleton h-9 w-full" />;
  }

  const checks = [
    { label: "DataHub", ok: status.datahubReachable, detail: status.datahubVersion ?? "" },
    { label: "Slack", ok: status.slackConfigured, detail: status.slackInteractiveApprovals ? "approvals on" : "notify only" },
    { label: "PagerDuty", ok: status.pagerdutyConfigured, detail: "" },
    { label: "LLM", ok: status.llmConfigured, detail: status.llmModel.split("/").pop() ?? "" },
  ];
  const down = checks.filter((c) => !c.ok).length;

  return (
    <div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs transition hover:bg-surface-hover"
      >
        <span className="flex items-center gap-2">
          <span className="relative flex h-1.5 w-1.5">
            <span
              className={`absolute inline-flex h-1.5 w-1.5 rounded-full ${
                down === 0 ? "bg-good pulse-live" : "bg-warn"
              }`}
            />
          </span>
          <span className={down === 0 ? "text-good" : "text-warn"}>
            {down === 0 ? "all systems live" : `${down} degraded`}
          </span>
        </span>
        <span className="text-muted-dim">{expanded ? "▾" : "▸"}</span>
      </button>

      {expanded && (
        <ul className="fade-up mt-1 space-y-1 rounded-lg bg-surface p-2">
          {checks.map((c) => (
            <li key={c.label} className="flex items-center justify-between text-[11px]">
              <span className="flex items-center gap-1.5">
                <span
                  className={`h-1 w-1 rounded-full ${c.ok ? "bg-good" : "bg-bad"}`}
                />
                <span className="text-muted">{c.label}</span>
              </span>
              <span className="max-w-[92px] truncate text-muted-dim" title={c.detail}>
                {c.detail || (c.ok ? "up" : "down")}
              </span>
            </li>
          ))}
          {status.webhookSourcesEnabled.length > 0 && (
            <li className="border-t border-border pt-1.5 text-[10px] text-muted-dim">
              {status.webhookSourcesEnabled.length} webhook sources
              {status.sweepIntervalMinutes > 0 && ` · ${status.sweepIntervalMinutes}m sweep`}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
