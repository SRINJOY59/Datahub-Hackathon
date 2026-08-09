"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import CommandPalette from "@/components/CommandPalette";
import AuthGuard from "@/components/AuthGuard";

const AUTH_PATHS = ["/login", "/signup"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthPage = AUTH_PATHS.includes(pathname);

  return (
    <AuthGuard>
      {isAuthPage ? (
        <main className="min-h-screen w-full">{children}</main>
      ) : (
        <>
          <div className="flex">
            <Sidebar />
            <main className="min-w-0 flex-1">{children}</main>
          </div>
          <CommandPalette />
        </>
      )}
    </AuthGuard>
  );
}
