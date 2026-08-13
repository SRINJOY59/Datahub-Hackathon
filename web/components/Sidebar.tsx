"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import StatusPill from "./StatusPill";
import RepoSelector from "./RepoSelector";

const NAV: { href: string; label: string; icon: React.ReactNode; group: string }[] = [
  { group: "Monitor", href: "/overview", label: "Overview", icon: <IconGrid /> },
  { group: "Monitor", href: "/incidents", label: "Incidents", icon: <IconAlert /> },
  { group: "Monitor", href: "/trends", label: "Trends", icon: <IconChart /> },
  { group: "Monitor", href: "/pipeline", label: "Pipeline", icon: <IconPipeline /> },
  { group: "Catalog", href: "/assets", label: "Asset health", icon: <IconShield /> },
  { group: "Catalog", href: "/api-health", label: "API health", icon: <IconApi /> },
  { group: "Catalog", href: "/runbooks", label: "Runbooks", icon: <IconBook /> },
  { group: "Operate", href: "/activity", label: "Activity", icon: <IconPulse /> },
  { group: "Operate", href: "/chat", label: "Ask on-call", icon: <IconChat /> },
  { group: "Explore", href: "/", label: "Product Home", icon: <IconHome /> },
];

export default function Sidebar({ onOpenConnectModal, onCloseMobile }: { onOpenConnectModal?: () => void; onCloseMobile?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, username, email, signOut } = useAuth();
  const groups = Array.from(new Set(NAV.map((n) => n.group)));

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
  };

  return (
    <aside className="sticky top-0 flex h-screen w-[228px] shrink-0 flex-col border-r border-border bg-surface/40">
      <div className="flex items-center justify-between px-5 py-4 border-b border-border/40">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="pulse-live absolute inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
          </span>
          <div>
            <p className="text-sm font-bold leading-none tracking-tight text-foreground flex items-center gap-1.5">
              <span>OmniSRE</span>
              <span className="rounded bg-accent-soft px-1.5 py-0.2 text-[9px] font-mono text-accent border border-accent/30">AI</span>
            </p>
            <p className="mt-1 text-[10px] leading-none text-muted-dim">
              multi-repo data & ml sre
            </p>
          </div>
        </div>
        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="rounded p-1 text-muted hover:bg-surface-hover hover:text-foreground md:hidden"
            aria-label="Close menu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>

      {/* Active Repo Switcher */}
      <div className="px-3 py-2.5 border-b border-border/40">
        <RepoSelector onOpenConnectModal={onOpenConnectModal} />
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin px-3">
        {groups.map((group) => (
          <div key={group} className="mb-5">
            <p className="px-2 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-dim">
              {group}
            </p>
            <div className="space-y-0.5">
              {NAV.filter((n) => n.group === group).map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onCloseMobile}
                    className={`group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                      active
                        ? "bg-accent-soft text-foreground"
                        : "text-muted hover:bg-surface-hover hover:text-foreground"
                    }`}
                  >
                    {active && (
                      <span className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-r bg-accent" />
                    )}
                    <span className={active ? "text-accent" : "text-muted-dim group-hover:text-muted"}>
                      {item.icon}
                    </span>
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* User profile & System status footer */}
      <div className="border-t border-border p-3 space-y-2.5">
        {user ? (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface-raised/60 p-2 text-xs">
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent font-semibold uppercase">
                {username ? username.charAt(0) : "O"}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-foreground leading-tight">
                  {username}
                </p>
                <p className="truncate text-[10px] text-muted-dim leading-tight mt-0.5">
                  {email || "operator"}
                </p>
              </div>
            </div>
            <button
              onClick={handleSignOut}
              title="Sign out of Sentinel"
              className="rounded p-1 text-muted-dim hover:bg-surface-hover hover:text-bad focus:outline-none transition"
            >
              <IconLogOut />
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="flex items-center justify-center gap-2 rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-xs font-medium text-muted hover:text-foreground transition"
          >
            <IconUser />
            <span>Sign In</span>
          </Link>
        )}
        <StatusPill />
      </div>
    </aside>
  );
}

function IconLogOut() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" x2="9" y1="12" y2="12" />
    </svg>
  );
}

function IconUser() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}


/* Inline 14px stroke icons — no icon dependency for seven glyphs. */
function base(children: React.ReactNode) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden>
      {children}
    </svg>
  );
}
function IconGrid() {
  return base(<><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></>);
}
function IconAlert() {
  return base(<><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>);
}
function IconChart() {
  return base(<><line x1="3" y1="21" x2="21" y2="21" /><polyline points="4,15 9,9 14,13 20,6" /></>);
}
function IconShield() {
  return base(<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />);
}
function IconBook() {
  return base(<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></>);
}
function IconPulse() {
  return base(<polyline points="22,12 18,12 15,21 9,3 6,12 2,12" />);
}
function IconPipeline() {
  return base(<><path d="M4 6h4M12 6h8M4 12h8M16 12h4M4 18h8M16 18h4" /><circle cx="10" cy="6" r="2" /><circle cx="14" cy="12" r="2" /><circle cx="14" cy="18" r="2" /></>);
}
function IconChat() {
  return base(<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />);
}
function IconApi() {
  return base(<><path d="m18 16 4-4-4-4" /><path d="m6 8-4 4 4 4" /><path d="m14.5 4-5 16" /></>);
}
function IconHome() {
  return base(<><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></>);
}
