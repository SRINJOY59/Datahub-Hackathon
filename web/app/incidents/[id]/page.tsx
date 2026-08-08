"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchIncident } from "@/lib/queries";
import type { Incident } from "@/lib/types";
import { StatusBadge, TierBadge } from "@/components/Badge";

const POLL_MS = 8_000;

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export default function IncidentDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [incident, setIncident] = useState<Incident | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchIncident(id)
        .then((data) => {
          if (cancelled) return;
          if (!data) setNotFound(true);
          else setIncident(data);
        })
        .catch(() => {});
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [id]);

  if (notFound) {
    return (
      <div className="px-8 py-16 max-w-4xl text-center">
        <p className="text-muted">No incident found with id {id}.</p>
        <Link href="/incidents" className="mt-4 inline-block text-accent hover:underline">
          ← back to incidents
        </Link>
      </div>
    );
  }

  if (!incident) {
    return <div className="px-8 py-16 max-w-4xl text-center text-muted">Loading…</div>;
  }

  return (
    <div className="px-8 py-7 max-w-4xl space-y-6">
      <Link href="/incidents" className="text-xs text-muted hover:text-foreground">
        ← incidents
      </Link>

      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-mono text-xl font-semibold">{incident.id}</h1>
          <StatusBadge status={incident.status} />
          <TierBadge tier={incident.tier} />
        </div>
        <p className="mt-1 text-sm text-muted">
          {incident.assetName ?? incident.assetUrn} ·{" "}
          {incident.changeType?.replace(/_/g, " ") ?? "unknown"} · confidence{" "}
          {incident.confidence ?? "n/a"}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MiniStat label="Cost exposure" value={incident.costUsd != null ? `$${Math.round(incident.costUsd).toLocaleString()}` : "—"} />
        <MiniStat label="Downstream" value={String(incident.downstreamCount ?? 0)} />
        <MiniStat label="Detected" value={fmt(incident.detectedAt)} small />
        <MiniStat label="Closed" value={fmt(incident.closedAt)} small />
      </div>

      {incident.narrative && (
        <section className="card p-5">
          <h2 className="text-sm font-medium text-muted">Root cause narrative</h2>
          <p className="mt-2 text-sm leading-relaxed">{incident.narrative}</p>
          {incident.rootCauseAsset && (
            <p className="mt-3 font-mono text-xs text-muted">
              root: {incident.rootCauseAsset}
              {incident.rootCauseColumn && `.${incident.rootCauseColumn}`}
            </p>
          )}
        </section>
      )}

      {incident.costBasis && (
        <section className="card p-5">
          <h2 className="text-sm font-medium text-muted">Cost basis</h2>
          <p className="mt-2 text-sm text-muted">{incident.costBasis}</p>
        </section>
      )}

      {incident.pr && (
        <section className="card p-5">
          <h2 className="text-sm font-medium text-muted">Fix for review</h2>
          <a
            href={incident.pr}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-block text-sm text-accent hover:underline"
          >
            {incident.pr}
          </a>
        </section>
      )}

      <section className="card p-5">
        <h2 className="text-sm font-medium text-muted">Action timeline</h2>
        {incident.timeline.length === 0 ? (
          <p className="mt-3 text-sm text-muted">No actions recorded.</p>
        ) : (
          <ol className="mt-4 space-y-4 border-l border-border pl-4">
            {incident.timeline.map((a, i) => (
              <li key={i} className="relative">
                <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-accent" />
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{a.actionType.replace(/_/g, " ")}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs ${
                      a.status === "applied"
                        ? "bg-good-soft text-good"
                        : a.status === "reverted"
                          ? "bg-warn-soft text-warn"
                          : a.status === "failed"
                            ? "bg-bad-soft text-bad"
                            : "bg-surface-raised text-muted"
                    }`}
                  >
                    {a.status}
                  </span>
                  {a.reversible && (
                    <span className="text-xs text-muted">reversible</span>
                  )}
                </div>
                <p className="mt-0.5 font-mono text-xs text-muted">{a.target}</p>
                {a.note && <p className="mt-1 text-xs text-muted">{a.note}</p>}
                {a.appliedAt && (
                  <p className="mt-0.5 text-[11px] text-muted">{fmt(a.appliedAt)}</p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function MiniStat({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div className="card p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 font-medium ${small ? "text-xs" : "text-lg"}`}>{value}</p>
    </div>
  );
}
