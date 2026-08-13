export default function PageHeader({
  title,
  subtitle,
  live,
  actions,
}: {
  title: string;
  subtitle?: string;
  live?: boolean;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <h1 className="text-lg font-semibold tracking-tight sm:text-[22px]">{title}</h1>
          {live && (
            <span className="flex items-center gap-1.5 rounded-full bg-good-soft px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-good">
              <span className="pulse-live h-1 w-1 rounded-full bg-good" />
              live
            </span>
          )}
        </div>
        {subtitle && <p className="mt-1.5 max-w-2xl text-xs text-muted sm:text-sm">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
