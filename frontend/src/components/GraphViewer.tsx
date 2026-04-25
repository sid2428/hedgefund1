import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import type { GraphResponse, GraphNode, GraphEdge } from "@/types/graph";

interface GraphViewerProps {
  data: GraphResponse;
  height?: number;
  onNodeClick?: (ticker: string) => void;
}

interface SimNode extends GraphNode, d3.SimulationNodeDatum {}
interface SimLink extends Omit<GraphEdge, "source" | "target">, d3.SimulationLinkDatum<SimNode> {
  source: string | SimNode;
  target: string | SimNode;
}

const sectorColors: Record<string, string> = {
  Semiconductors: "#22d3ee",
};

const edgeColors: Record<string, string> = {
  customer: "#10b981",
  supplier: "#ef4444",
  competitor: "#f59e0b",
  partner: "#a855f7",
  sector_peer: "#475569",
  geographic_peer: "#64748b",
};

export default function GraphViewer({
  data,
  height = 560,
  onNodeClick,
}: GraphViewerProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoverEdge, setHoverEdge] = useState<SimLink | null>(null);

  const { nodes, links } = useMemo(() => {
    const nodes = data.nodes.map((n) => ({ ...n })) as SimNode[];
    const links = data.links.map((e) => ({ ...e })) as unknown as SimLink[];
    return { nodes, links };
  }, [data]);

  useEffect(() => {
    if (!svgRef.current || !wrapperRef.current || nodes.length === 0) return;

    const width = wrapperRef.current.clientWidth || 800;
    const svg = d3
      .select(svgRef.current)
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("width", "100%")
      .attr("height", height);
    svg.selectAll("*").remove();

    const g = svg.append("g");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.4, 4])
      .on("zoom", (event) => g.attr("transform", event.transform.toString()));
    svg.call(zoom);

    // arrow marker for directed edges
    g.append("defs")
      .selectAll("marker")
      .data(Object.keys(edgeColors))
      .join("marker")
      .attr("id", (d) => `arrow-${d}`)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 16)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", (d) => edgeColors[d] || "#94a3b8");

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance(100)
          .strength(0.4)
      )
      .force("charge", d3.forceManyBody().strength(-260))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(28));

    const link = g
      .append("g")
      .attr("stroke-opacity", 0.7)
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => edgeColors[d.type] || "#94a3b8")
      .attr("stroke-width", (d) => 1 + (d.strength || 1) * 1.2)
      .attr("marker-end", (d) => `url(#arrow-${d.type})`)
      .on("mouseover", (_e, d) => setHoverEdge(d))
      .on("mouseout", () => setHoverEdge(null));

    const radiusFor = (d: SimNode) => {
      const cap = d.market_cap || 0;
      if (cap > 1e12) return 22;
      if (cap > 1e11) return 16;
      if (cap > 1e10) return 12;
      return 9;
    };

    const node = g
      .append("g")
      .attr("stroke", "#0b0f17")
      .attr("stroke-width", 1.5)
      .selectAll("circle")
      .data(nodes)
      .join("circle")
      .attr("r", radiusFor)
      .attr("fill", (d) => sectorColors[d.sector || ""] || "#22d3ee")
      .style("cursor", "pointer")
      .on("click", (_e, d) => onNodeClick?.(d.id))
      .call(
        d3
          .drag<SVGCircleElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    node.append("title").text((d) => `${d.id} — ${d.name}`);

    const label = g
      .append("g")
      .selectAll("text")
      .data(nodes)
      .join("text")
      .text((d) => d.id)
      .attr("font-size", 10)
      .attr("font-family", "JetBrains Mono, monospace")
      .attr("fill", "#e2e8f0")
      .attr("pointer-events", "none")
      .attr("dy", -14)
      .attr("text-anchor", "middle");

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);
      node.attr("cx", (d) => d.x ?? 0).attr("cy", (d) => d.y ?? 0);
      label.attr("x", (d) => d.x ?? 0).attr("y", (d) => d.y ?? 0);
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, links, height, onNodeClick]);

  return (
    <div ref={wrapperRef} className="relative w-full">
      <svg ref={svgRef} className="w-full bg-mosaic-bg/40 rounded-md border border-mosaic-border" />
      {hoverEdge && (
        <div className="absolute top-2 right-2 max-w-sm text-xs bg-mosaic-panel border border-mosaic-border p-2 rounded-md">
          <div>
            <span className="font-mono">{(hoverEdge.source as SimNode).id ?? hoverEdge.source}</span>{" "}
            → <span className="font-mono">{(hoverEdge.target as SimNode).id ?? hoverEdge.target}</span>
          </div>
          <div className="text-mosaic-mute">type: {hoverEdge.type}</div>
          {hoverEdge.evidence && (
            <div className="text-slate-300 italic mt-1">“{hoverEdge.evidence}”</div>
          )}
        </div>
      )}
    </div>
  );
}
