import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import type { EvidenceStep } from "@/types/thesis";

export default function EvidenceChain({ steps }: { steps: EvidenceStep[] }) {
  const [open, setOpen] = useState(true);
  if (!steps || steps.length === 0) {
    return <div className="text-xs text-mosaic-mute">No evidence chain available.</div>;
  }
  return (
    <div className="border border-mosaic-border rounded-md bg-mosaic-panel/60">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-3 py-2 flex items-center justify-between text-sm hover:bg-mosaic-panel"
      >
        <span className="flex items-center gap-2 font-medium">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Evidence chain ({steps.length} step{steps.length === 1 ? "" : "s"})
        </span>
      </button>
      {open && (
        <ol className="divide-y divide-mosaic-border">
          {steps.map((s) => (
            <li key={s.step} className="px-4 py-3 text-sm">
              <div className="flex items-start gap-3">
                <span className="font-mono text-xs text-mosaic-accent mt-0.5">
                  #{s.step}
                </span>
                <div className="flex-1 space-y-1">
                  <div>{s.description}</div>
                  <blockquote className="text-xs text-slate-300 border-l-2 border-mosaic-border pl-2 italic">
                    “{s.quote}”
                  </blockquote>
                  <div className="flex items-center gap-2 text-xs text-mosaic-mute">
                    <FileText size={12} />
                    <span>{s.source_company}</span>
                    <span>·</span>
                    <span>{s.source_filing}</span>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
