import { create } from "zustand";
import type { ThesisDirection, ThesisStatus } from "@/types/thesis";

interface AppState {
  filterStatus: ThesisStatus | "all";
  filterDirection: ThesisDirection | "all";
  confidenceMin: number;
  selectedThesisId: string | null;
  setFilterStatus: (s: ThesisStatus | "all") => void;
  setFilterDirection: (d: ThesisDirection | "all") => void;
  setConfidenceMin: (n: number) => void;
  selectThesis: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  filterStatus: "pending",
  filterDirection: "all",
  confidenceMin: 0,
  selectedThesisId: null,
  setFilterStatus: (s) => set({ filterStatus: s }),
  setFilterDirection: (d) => set({ filterDirection: d }),
  setConfidenceMin: (n) => set({ confidenceMin: n }),
  selectThesis: (id) => set({ selectedThesisId: id }),
}));
