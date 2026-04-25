export interface GraphNode {
  id: string;            // ticker
  name: string;
  sector: string | null;
  market_cap: number | null;
}

export interface GraphEdge {
  source: string;        // ticker
  target: string;        // ticker
  type: string;          // 'customer' | 'supplier' | 'sector_peer' | ...
  strength: number;
  evidence: string | null;
}

export interface GraphResponse {
  nodes: GraphNode[];
  links: GraphEdge[];
}
