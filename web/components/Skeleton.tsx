export function SkeletonTile() {
  return (
    <div className="card p-5">
      <div className="skeleton h-3 w-24" />
      <div className="skeleton mt-4 h-7 w-16" />
    </div>
  );
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-12 w-full" style={{ opacity: 1 - i * 0.13 }} />
      ))}
    </div>
  );
}

export function SkeletonBlock({ height = 180 }: { height?: number }) {
  return <div className="skeleton w-full" style={{ height }} />;
}
