"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { fetchIncidents } from "@/lib/queries";
import type { Incident } from "@/lib/types";
import { StatusBadge, TierBadge } from "@/components/Badge";

type SortKey = "detectedAt" | "costUsd" | "status";

const STATUS_FILTERS = ["all", "open", "resolved", "contained", "escalated", "rolled_back"];

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("detectedAt");
  const [sortDesc, setSortDesc] = useState(true);

  useEffect(() => {
    fetchIncidents({ limit: 200 })
      .then((data) => {
        setIncidents(data);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    let rows = incidents;
    if (statusFilter !== "all") rows = rows.filter((r) => r.status === statusFilter);
    if (query.trim()) {
      const q = query.toLowerCase();
      rows = rows.filter(
        (r) =>
          r.id.toLowerCase().includes(q) ||
          (r.assetName ?? "").toLowerCase().includes(q) ||
          r.assetUrn.toLowerCase().includes(q) ||
          (r.changeType ?? "").toLowerCase().includes(q) ||
          (r.narrative ?? "").toLowerCase().includes(q),
      );
    }
    const sorted = [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "detectedAt") cmp = a.detectedAt.localeCompare(b.detectedAt);
      else if (sortKey === "costUsd") cmp = (a.costUsd ?? 0) - (b.costUsd ?? 0);
      else if (sortKey === "status") cmp = a.status.localeCompare(b.status);
      return sortDesc ? -cmp : cmp;
    });
    return sorted;
  }, [incidents, statusFilter, query, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setSortDesc((d) => !d);
    else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  return (
    <div className="px-8 py-7 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Incidents</h1>
          <p className="mt-1 text-sm text-muted">
            {filtered.length} of {incidents.length}
          </p>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search asset, id, change type…"
          className="w-72 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              statusFilter === s
                ? "border-accent bg-accent-soft text-accent"
                : "border-border text-muted hover:text-foreground"
            }`}
          >
            {s.replace("_", " ")}
          </button>
        ))}
      </div>

      {error && (
        <div className="card border-bad/40 bg-bad-soft p-4 text-sm text-bad">
          Can&apos;t reach the backend.
        </div>
      )}

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="px-4 py-3 font-medium">Incident</th>
              <th className="px-4 py-3 font-medium">Asset</th>
              <th className="px-4 py-3 font-medium">Change type</th>
              <th className="px-4 py-3 font-medium">Tier</th>
              <th
                className="cursor-pointer select-none px-4 py-3 font-medium hover:text-foreground"
                onClick={() => toggleSort("status")}
              >
                Status {sortKey === "status" && (sortDesc ? "↓" : "↑")}
              </th>
              <th
                className="cursor-pointer select-none px-4 py-3 text-right font-medium hover:text-foreground"
                onClick={() => toggleSort("costUsd")}
              >
                Cost {sortKey === "costUsd" && (sortDesc ? "↓" : "↑")}
              </th>
              <th
                className="cursor-pointer select-none px-4 py-3 text-right font-medium hover:text-foreground"
                onClick={() => toggleSort("detectedAt")}
              >
                Detected {sortKey === "detectedAt" && (sortDesc ? "↓" : "↑")}
              </th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">
                  No incidents match.
                </td>
              </tr>
            )}
            {filtered.map((inc) => (
              <tr
                key={inc.id}
                className="cursor-pointer border-b border-border last:border-0 hover:bg-surface-raised"
                onClick={() => (window.location.href = `/incidents/${inc.id}`)}
              >
                <td className="px-4 py-3">
                  <Link href={`/incidents/${inc.id}`} className="font-mono text-xs text-accent">
                    {inc.id}
                  </Link>
                </td>
                <td className="max-w-[220px] truncate px-4 py-3">
                  {inc.assetName ?? inc.assetUrn}
                </td>
                <td className="px-4 py-3 text-muted">
                  {inc.changeType?.replace(/_/g, " ") ?? "—"}
                </td>
                <td className="px-4 py-3">
                  <TierBadge tier={inc.tier} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={inc.status} />
                </td>
                <td className="px-4 py-3 text-right tabular-nums">
                  {inc.costUsd != null ? `$${Math.round(inc.costUsd).toLocaleString()}` : "—"}
                </td>
                <td className="px-4 py-3 text-right text-xs text-muted tabular-nums">
                  {new Date(inc.detectedAt).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
