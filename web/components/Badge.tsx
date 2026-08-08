const STATUS_STYLE: Record<string, string> = {
  resolved: "text-good bg-good-soft",
  open: "text-info bg-info-soft",
  contained: "text-warn bg-warn-soft",
  escalated: "text-bad bg-bad-soft",
  rolled_back: "text-bad bg-bad-soft",
  correlated: "text-muted bg-surface-raised",
  simulated: "text-muted bg-surface-raised",
};

const TIER_STYLE: Record<string, string> = {
  auto: "text-good bg-good-soft",
  pr_only: "text-warn bg-warn-soft",
  human_only: "text-bad bg-bad-soft",
};

function chip(label: string, style: string) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}
    >
      {label}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return chip(status.replace("_", " "), STATUS_STYLE[status] ?? "text-muted bg-surface-raised");
}

export function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  return chip(tier.replace("_", " "), TIER_STYLE[tier] ?? "text-muted bg-surface-raised");
}

export function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-good" : "bg-bad"}`}
      aria-hidden
    />
  );
}
