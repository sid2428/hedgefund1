import clsx from "clsx";

export default function ConfidenceScore({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value));
  const tone =
    pct >= 0.67
      ? "bg-mosaic-long"
      : pct >= 0.34
      ? "bg-mosaic-warn"
      : "bg-mosaic-short";

  return (
    <div className="flex items-center gap-2 w-32" title={`${(pct * 100).toFixed(0)}% confidence`}>
      <div className="h-1.5 flex-1 rounded-full bg-mosaic-border overflow-hidden">
        <div className={clsx("h-full rounded-full", tone)} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-300 w-10 text-right">
        {(pct * 100).toFixed(0)}%
      </span>
    </div>
  );
}
