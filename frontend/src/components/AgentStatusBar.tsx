import { Activity, Database } from "lucide-react";
import { useThesisStats } from "@/hooks/useTheses";

export default function AgentStatusBar() {
  const { data, isLoading } = useThesisStats();
  return (
    <div className="border-t border-mosaic-border bg-mosaic-bg/60 text-xs text-mosaic-mute">
      <div className="max-w-7xl mx-auto px-6 py-1.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity size={12} className="text-mosaic-accent" />
          <span>Pipeline live</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            <Database size={12} />
            theses: {isLoading ? "…" : data?.total ?? 0}
          </span>
          <span>pending: {isLoading ? "…" : data?.pending ?? 0}</span>
          <span className="text-mosaic-long">validated: {isLoading ? "…" : data?.validated ?? 0}</span>
          <span className="text-mosaic-short">dismissed: {isLoading ? "…" : data?.dismissed ?? 0}</span>
        </div>
      </div>
    </div>
  );
}
