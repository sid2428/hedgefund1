import { useNavigate, useParams } from "react-router-dom";
import GraphViewer from "@/components/GraphViewer";
import { useEgoGraph, useFullGraph } from "@/hooks/useCompanyGraph";

export default function CompanyGraph() {
  const { ticker } = useParams<{ ticker?: string }>();
  const navigate = useNavigate();
  const ego = useEgoGraph(ticker);
  const full = useFullGraph();

  const data = ticker ? ego.data : full.data;
  const isLoading = ticker ? ego.isLoading : full.isLoading;
  const error = ticker ? ego.error : full.error;

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Relationship graph {ticker && <span className="text-mosaic-accent">/ {ticker}</span>}
          </h1>
          <p className="text-sm text-mosaic-mute">
            {ticker
              ? `2-degree neighbourhood of ${ticker}.`
              : "Click a node to drill into its 2-degree neighbourhood. Drag to rearrange."}
          </p>
        </div>
        {ticker && (
          <button
            onClick={() => navigate("/graph")}
            className="text-sm text-mosaic-accent hover:underline"
          >
            ← full graph
          </button>
        )}
      </header>

      {error && (
        <div className="text-sm text-mosaic-short border border-mosaic-short/40 bg-mosaic-short/10 rounded-md p-3">
          Failed to load graph: {(error as any).detail || String(error)}
        </div>
      )}

      {isLoading ? (
        <div className="border border-mosaic-border rounded-md h-[560px] animate-pulse bg-mosaic-panel/40" />
      ) : data && data.nodes.length > 0 ? (
        <GraphViewer data={data} onNodeClick={(t) => navigate(`/graph/${t}`)} />
      ) : (
        <div className="border border-dashed border-mosaic-border rounded-md p-12 text-center text-mosaic-mute">
          Graph is empty. Run the demo or ingest a company to populate edges.
        </div>
      )}

      <Legend />
    </div>
  );
}

function Legend() {
  const items: { label: string; color: string }[] = [
    { label: "customer", color: "#10b981" },
    { label: "supplier", color: "#ef4444" },
    { label: "competitor", color: "#f59e0b" },
    { label: "partner", color: "#a855f7" },
    { label: "sector_peer", color: "#475569" },
  ];
  return (
    <div className="flex flex-wrap gap-3 text-xs text-mosaic-mute">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1">
          <span className="inline-block w-4 h-0.5" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
