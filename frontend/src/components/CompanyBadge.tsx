import clsx from "clsx";
import { Link } from "react-router-dom";

export interface CompanyBadgeProps {
  ticker: string;
  name?: string;
  variant?: "trigger" | "affected" | "neutral";
  linkable?: boolean;
}

const variants: Record<NonNullable<CompanyBadgeProps["variant"]>, string> = {
  trigger: "bg-mosaic-accent/10 border-mosaic-accent/40 text-mosaic-accent",
  affected: "bg-mosaic-warn/10 border-mosaic-warn/40 text-mosaic-warn",
  neutral: "bg-mosaic-panel border-mosaic-border text-slate-200",
};

export default function CompanyBadge({
  ticker,
  name,
  variant = "neutral",
  linkable = true,
}: CompanyBadgeProps) {
  const inner = (
    <span
      className={clsx(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs font-mono",
        variants[variant]
      )}
      title={name}
    >
      <span className="font-semibold">{ticker}</span>
      {name && <span className="hidden md:inline text-slate-400 truncate max-w-[14ch]">{name}</span>}
    </span>
  );
  if (!linkable) return inner;
  return <Link to={`/graph/${ticker}`}>{inner}</Link>;
}
