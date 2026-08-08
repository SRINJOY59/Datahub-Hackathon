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
    <div className="flex items-start justify-between gap-6 border-b border-border pb-5">
      <div>
        <div className="flex items-center gap-2.5">
          <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
          {live && (
            <span className="flex items-center gap-1.5 rounded-full bg-good-soft px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-good">
              <span className="pulse-live h-1 w-1 rounded-full bg-good" />
              live
            </span>
          )}
        </div>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
