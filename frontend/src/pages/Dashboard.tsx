import { useMemo } from "react";
import clsx from "clsx";
import ThesisCard from "@/components/ThesisCard";
import { useDismissThesis, useTheses, useValidateThesis } from "@/hooks/useTheses";
import { useAppStore } from "@/store/appStore";

const statusFilters = [
  { label: "All", value: "all" },
  { label: "Pending", value: "pending" },
  { label: "Validated", value: "validated" },
  { label: "Dismissed", value: "dismissed" },
] as const;

const directionFilters = [
  { label: "All directions", value: "all" },
  { label: "Long", value: "long" },
  { label: "Short", value: "short" },
  { label: "Pairs", value: "long_short_pair" },
] as const;

const confidenceTiers = [
  { label: "Any", value: 0 },
  { label: "≥ 0.5", value: 0.5 },
  { label: "≥ 0.7 (high)", value: 0.7 },
];

export default function Dashboard() {
  const {
    filterStatus,
    filterDirection,
    confidenceMin,
    setFilterStatus,
    setFilterDirection,
    setConfidenceMin,
  } = useAppStore();

  const filters = useMemo(
    () => ({
      status: filterStatus === "all" ? undefined : filterStatus,
      direction: filterDirection === "all" ? undefined : filterDirection,
      confidence_min: confidenceMin > 0 ? confidenceMin : undefined,
      limit: 50,
    }),
    [filterStatus, filterDirection, confidenceMin]
  );

  const { data, isLoading, error } = useTheses(filters);
  const validate = useValidateThesis();
  const dismiss = useDismissThesis();

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Thesis feed</h1>
          <p className="text-sm text-mosaic-mute">
            Cross-company theses generated from filings. Validate or dismiss to teach the system.
          </p>
        </div>
        <div className="text-sm text-mosaic-mute">
          {data ? `${data.total} total` : ""}
        </div>
      </header>

      <div className="flex flex-wrap gap-2 items-center">
        {statusFilters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilterStatus(f.value as any)}
            className={clsx(
              "px-3 py-1.5 text-xs rounded-md border",
              filterStatus === f.value
                ? "border-mosaic-accent text-mosaic-accent bg-mosaic-accent/10"
                : "border-mosaic-border text-mosaic-mute hover:text-slate-100"
            )}
          >
            {f.label}
          </button>
        ))}
        <span className="w-px h-5 bg-mosaic-border mx-1" />
        {directionFilters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilterDirection(f.value as any)}
            className={clsx(
              "px-3 py-1.5 text-xs rounded-md border",
              filterDirection === f.value
                ? "border-mosaic-accent text-mosaic-accent bg-mosaic-accent/10"
                : "border-mosaic-border text-mosaic-mute hover:text-slate-100"
            )}
          >
            {f.label}
          </button>
        ))}
        <span className="w-px h-5 bg-mosaic-border mx-1" />
        {confidenceTiers.map((t) => (
          <button
            key={t.value}
            onClick={() => setConfidenceMin(t.value)}
            className={clsx(
              "px-3 py-1.5 text-xs rounded-md border",
              confidenceMin === t.value
                ? "border-mosaic-accent text-mosaic-accent bg-mosaic-accent/10"
                : "border-mosaic-border text-mosaic-mute hover:text-slate-100"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="text-sm text-mosaic-short border border-mosaic-short/40 bg-mosaic-short/10 rounded-md p-3">
          Failed to load theses: {(error as any).detail || String(error)}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="border border-mosaic-border bg-mosaic-panel rounded-md h-32 animate-pulse"
            />
          ))}
        </div>
      ) : data && data.theses.length > 0 ? (
        <div className="space-y-3">
          {data.theses.map((t) => (
            <ThesisCard
              key={t.id}
              thesis={t}
              onValidate={(id) => validate.mutate({ id })}
              onDismiss={(id) => dismiss.mutate({ id })}
            />
          ))}
        </div>
      ) : (
        <div className="border border-dashed border-mosaic-border rounded-md p-8 text-center text-mosaic-mute">
          No theses yet. Ingest a company on the Watchlist tab to get started.
        </div>
      )}
    </div>
  );
}
