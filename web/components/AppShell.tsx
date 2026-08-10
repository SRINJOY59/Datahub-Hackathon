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

  return (
    <AuthGuard>
      {isFullWidth ? (
        <main className="min-h-screen w-full">{children}</main>
      ) : (
        <>
          <div className="flex">
            <Sidebar onOpenConnectModal={() => setConnectModalOpen(true)} />
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
