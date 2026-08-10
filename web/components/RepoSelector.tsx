"use client";

import { useEffect, useState, useRef } from "react";
import { fetchConnectedRepositories, switchActiveRepository } from "@/lib/queries";
import type { ConnectedRepository } from "@/lib/types";

interface RepoSelectorProps {
  onOpenConnectModal?: () => void;
}

export default function RepoSelector({ onOpenConnectModal }: RepoSelectorProps) {
  const [repos, setRepos] = useState<ConnectedRepository[]>([]);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const loadRepos = () => {
    fetchConnectedRepositories()
      .then((data) => {
        if (data && data.length > 0) {
          setRepos(data);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    loadRepos();
    const handleOutsideClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const activeRepo = repos.find((r) => r.isActive) || repos[0] || {
    id: "default",
    repoName: "DataHub",
    commitSha: "head",
    datasetsCount: 6,
    modelsCount: 2,
    jobsCount: 3,
    isActive: true,
  };

  const handleSelectRepo = async (repoId: string) => {
    if (repoId === activeRepo.id) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    try {
      await switchActiveRepository(repoId);
      setRepos((prev) =>
        prev.map((r) => ({
          ...r,
          isActive: r.id === repoId,
        }))
      );
      setOpen(false);
      // Notify active pages to re-fetch context
      window.dispatchEvent(new CustomEvent("sentinel:repo-switched", { detail: { repoId } }));
      window.location.reload();
    } catch {
      // Ignore
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        disabled={switching}
        className="flex items-center gap-2 rounded-lg border border-border/80 bg-surface px-3 py-1.5 text-xs font-medium text-foreground shadow-sm hover:border-accent/60 hover:bg-surface-raised transition"
      >
        <span className="flex h-2 w-2 rounded-full bg-good animate-pulse" />
        <span className="text-muted font-normal text-[11px]">Repo:</span>
        <span className="font-semibold text-foreground truncate max-w-[140px]">{activeRepo.repoName}</span>
        <span className="text-[10px] text-muted ml-0.5">▾</span>
      </button>

      {open && (
        <div className="absolute left-0 mt-2 z-50 w-72 rounded-xl border border-border-strong bg-surface p-2 shadow-2xl space-y-1">
          <div className="px-2 py-1.5 text-[11px] font-semibold text-muted uppercase tracking-wider border-b border-border/60">
            Connected Repositories
          </div>

          <div className="max-h-60 overflow-y-auto space-y-1 scrollbar-thin py-1">
            {repos.map((r) => {
              const isSelected = r.id === activeRepo.id;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => handleSelectRepo(r.id)}
                  className={`w-full flex items-center justify-between rounded-lg p-2 text-left text-xs transition ${
                    isSelected
                      ? "bg-accent-soft/30 border border-accent/40 text-foreground"
                      : "hover:bg-surface-raised text-muted hover:text-foreground"
                  }`}
                >
                  <div className="min-w-0 pr-2">
                    <div className="flex items-center gap-1.5">
                      {isSelected && <span className="text-good font-bold text-[10px]">✓</span>}
                      <p className="font-medium text-foreground truncate">{r.repoName}</p>
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-[10px] text-muted">
                      <span>{r.datasetsCount} datasets</span>
                      <span>•</span>
                      <span>{r.modelsCount} models</span>
                      {r.commitSha && (
                        <>
                          <span>•</span>
                          <span className="font-mono">{r.commitSha}</span>
                        </>
                      )}
                    </div>
                  </div>
                  {isSelected && (
                    <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[9px] font-semibold text-accent uppercase shrink-0">
                      Active
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="pt-1.5 border-t border-border/60">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                if (onOpenConnectModal) onOpenConnectModal();
              }}
              className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-border py-1.5 text-xs text-accent hover:border-accent hover:bg-accent-soft/20 transition font-medium"
            >
              <span>+</span>
              <span>Connect New Repository...</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
