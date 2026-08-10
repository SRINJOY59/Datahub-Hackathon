"use client";

import React, { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const PUBLIC_PATHS = ["/", "/login", "/signup"];
const AUTH_FLOW_PATHS = ["/login", "/signup"];

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublicPath = PUBLIC_PATHS.includes(pathname);
  const isAuthFlow = AUTH_FLOW_PATHS.includes(pathname);

  useEffect(() => {
    if (loading) return;

    if (!user && !isPublicPath) {
      router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
    } else if (user && isAuthFlow) {
      router.replace("/overview");
    }
  }, [user, loading, pathname, isPublicPath, isAuthFlow, router]);

  // While checking auth status on protected pages, show a sleek loader
  if (loading && !isPublicPath) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="relative flex h-10 w-10 items-center justify-center">
            <span className="absolute h-10 w-10 animate-ping rounded-full bg-accent/20" />
            <span className="h-6 w-6 rounded-full border-2 border-accent border-t-transparent animate-spin" />
          </div>
          <p className="text-xs font-medium tracking-wide uppercase text-muted">
            Verifying Sentinel Session...
          </p>
        </div>
      </div>
    );
  }

  // If not logged in and not on a public path, don't flash protected UI while redirecting
  if (!user && !isPublicPath) {
    return null;
  }

  return <>{children}</>;
}
