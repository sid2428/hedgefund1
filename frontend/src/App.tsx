import { NavLink, Route, Routes } from "react-router-dom";
import { Activity, Network, ListChecks, Eye } from "lucide-react";
import Dashboard from "./pages/Dashboard";
import ThesisDetail from "./pages/ThesisDetail";
import CompanyGraph from "./pages/CompanyGraph";
import Watchlist from "./pages/Watchlist";
import AgentStatusBar from "./components/AgentStatusBar";

const navItem =
  "flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-mosaic-panel transition-colors";
const activeItem = "bg-mosaic-panel text-mosaic-accent";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-mosaic-border bg-mosaic-panel">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/mosaic.svg" alt="Mosaic" className="w-7 h-7" />
            <span className="font-semibold tracking-tight text-lg">Mosaic</span>
            <span className="text-xs text-mosaic-mute hidden sm:inline">
              cross-company thesis engine
            </span>
          </div>
          <nav className="flex items-center gap-1">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `${navItem} ${isActive ? activeItem : ""}`
              }
            >
              <ListChecks size={16} /> Dashboard
            </NavLink>
            <NavLink
              to="/graph"
              className={({ isActive }) =>
                `${navItem} ${isActive ? activeItem : ""}`
              }
            >
              <Network size={16} /> Graph
            </NavLink>
            <NavLink
              to="/watchlist"
              className={({ isActive }) =>
                `${navItem} ${isActive ? activeItem : ""}`
              }
            >
              <Eye size={16} /> Watchlist
            </NavLink>
          </nav>
        </div>
        <AgentStatusBar />
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/theses/:id" element={<ThesisDetail />} />
          <Route path="/graph" element={<CompanyGraph />} />
          <Route path="/graph/:ticker" element={<CompanyGraph />} />
          <Route path="/watchlist" element={<Watchlist />} />
        </Routes>
      </main>

      <footer className="border-t border-mosaic-border text-xs text-mosaic-mute py-3 text-center">
        <Activity size={12} className="inline mr-1" />
        Mosaic MVP — evidence-backed cross-company theses from SEC filings
      </footer>
    </div>
  );
}
