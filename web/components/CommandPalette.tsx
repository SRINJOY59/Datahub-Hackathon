"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchIncidents } from "@/lib/queries";
import type { Incident } from "@/lib/types";

const PAGES = [
  { label: "Overview", href: "/", hint: "stats, health, recent" },
  { label: "Incidents", href: "/incidents", hint: "search and filter" },
  { label: "Trends", href: "/trends", hint: "volume, exposure, MTTR" },
  { label: "Asset health", href: "/assets", hint: "trust scores" },
  { label: "Runbooks", href: "/runbooks", hint: "synthesised procedures" },
  { label: "Activity", href: "/activity", hint: "journal and controls" },
  { label: "Ask on-call", href: "/chat", hint: "chat over incidents" },
];

export default function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => {
          if (!v) {
            setQuery("");
            setCursor(0);
          }
          return !v;
        });
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open && incidents.length === 0) {
      fetchIncidents({ limit: 50 }).then(setIncidents).catch(() => {});
    }
  }, [open, incidents.length]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pages = PAGES.filter(
      (p) => !q || p.label.toLowerCase().includes(q) || p.hint.includes(q),
    ).map((p) => ({ kind: "page" as const, label: p.label, sub: p.hint, href: p.href }));

    const incs = incidents
      .filter(
        (i) =>
          !q ||
          i.id.toLowerCase().includes(q) ||
          (i.assetName ?? "").toLowerCase().includes(q) ||
          (i.changeType ?? "").toLowerCase().includes(q),
      )
      .slice(0, 6)
      .map((i) => ({
        kind: "incident" as const,
        label: i.id,
        sub: `${i.assetName ?? ""} · ${i.changeType ?? ""} · ${i.status}`,
        href: `/incidents/${i.id}`,
      }));

    return [...pages, ...incs];
  }, [query, incidents]);

  const activeIndex = Math.min(cursor, Math.max(0, results.length - 1));

  if (!open) return null;

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="fade-up w-full max-w-lg overflow-hidden rounded-xl border border-border-strong bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(c + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(c - 1, 0));
            } else if (e.key === "Enter" && results[activeIndex]) {
              go(results[activeIndex].href);
            }
          }}
          placeholder="Jump to a page or incident…"
          className="w-full border-b border-border bg-transparent px-4 py-3.5 text-sm outline-none placeholder:text-muted-dim"
        />
        <ul className="max-h-80 overflow-y-auto scrollbar-thin py-1.5">
          {results.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-muted">No matches</li>
          )}
          {results.map((r, i) => (
            <li key={`${r.kind}-${r.label}`}>
              <button
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(r.href)}
                className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                  i === activeIndex ? "bg-accent-soft" : ""
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] ${
                      r.kind === "incident"
                        ? "bg-surface text-accent font-mono"
                        : "bg-surface text-muted-dim"
                    }`}
                  >
                    {r.kind === "incident" ? "INC" : "GO"}
                  </span>
                  {r.label}
                </span>
                <span className="truncate pl-3 text-xs text-muted-dim">{r.sub}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="border-t border-border px-4 py-2 text-[11px] text-muted-dim">
          <kbd className="rounded bg-surface px-1">↑↓</kbd> navigate ·{" "}
          <kbd className="rounded bg-surface px-1">↵</kbd> open ·{" "}
          <kbd className="rounded bg-surface px-1">esc</kbd> close
        </div>
      </div>
    </div>
  );
}
