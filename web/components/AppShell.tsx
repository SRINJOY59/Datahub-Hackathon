"use client";

import React, { useState } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import CommandPalette from "@/components/CommandPalette";
import OnboardRepoModal from "@/components/OnboardRepoModal";
import AuthGuard from "@/components/AuthGuard";

const FULL_WIDTH_PATHS = ["/", "/login", "/signup"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isFullWidth = FULL_WIDTH_PATHS.includes(pathname);
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <AuthGuard>
      {isFullWidth ? (
        <main className="min-h-screen w-full">{children}</main>
      ) : (
        <>
          {/* Mobile top bar */}
          <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-surface/95 px-4 py-3 backdrop-blur-sm md:hidden">
            <button
              onClick={() => setSidebarOpen(true)}
              className="rounded-md p-1 text-muted hover:bg-surface-hover hover:text-foreground"
              aria-label="Open menu"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="pulse-live absolute inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
              <span className="text-sm font-bold tracking-tight text-foreground">OmniSRE</span>
              <span className="rounded bg-accent-soft px-1 py-0.5 text-[8px] font-mono text-accent border border-accent/30">AI</span>
            </div>
          </div>

          <div className="flex">
            {/* Backdrop overlay for mobile sidebar */}
            {sidebarOpen && (
              <div
                className="fixed inset-0 z-40 bg-black/50 md:hidden"
                onClick={() => setSidebarOpen(false)}
              />
            )}

            {/* Sidebar: always visible on md+, slide-in drawer on mobile */}
            <div
              className={`fixed inset-y-0 left-0 z-50 transform transition-transform duration-200 md:static md:translate-x-0 ${
                sidebarOpen ? "translate-x-0" : "-translate-x-full"
              }`}
            >
              <Sidebar
                onOpenConnectModal={() => setConnectModalOpen(true)}
                onCloseMobile={() => setSidebarOpen(false)}
              />
            </div>

            <main className="min-w-0 flex-1">{children}</main>
          </div>
          <CommandPalette />
          <OnboardRepoModal
            open={connectModalOpen}
            onClose={() => setConnectModalOpen(false)}
            onSuccess={() => {
              window.location.reload();
            }}
          />
        </>
      )}
    </AuthGuard>
  );
}
