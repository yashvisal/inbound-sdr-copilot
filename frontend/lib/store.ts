"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { getAnalysisId } from "@/lib/api/id";
import type { LeadAnalysis } from "@/lib/api/types";

type AnalyzeStatus = "idle" | "loading" | "error";

interface LeadStoreState {
  analyses: LeadAnalysis[];
  status: AnalyzeStatus;
  error: string | null;
  personalizedIds: string[];
  setAnalyses: (list: LeadAnalysis[], options?: { personalized?: boolean }) => void;
  addAnalyses: (list: LeadAnalysis[], options?: { personalized?: boolean }) => void;
  updateAnalysis: (id: string, patch: Partial<LeadAnalysis>) => void;
  markPersonalized: (id: string) => void;
  setStatus: (status: AnalyzeStatus, error?: string | null) => void;
  clear: () => void;
}

function sortByScore(list: LeadAnalysis[]): LeadAnalysis[] {
  return [...list].sort((a, b) => b.score.final_score - a.score.final_score);
}

export const useLeadStore = create<LeadStoreState>()(
  persist(
    (set, get) => ({
      analyses: [],
      status: "idle",
      error: null,
      personalizedIds: [],
      setAnalyses: (list, options) =>
        set({
          analyses: sortByScore(list),
          personalizedIds: options?.personalized
            ? list.map((analysis) => getAnalysisId(analysis))
            : get().personalizedIds,
          status: "idle",
          error: null,
        }),
      addAnalyses: (list, options) => {
        const map = new Map(
          get().analyses.map((analysis) => [getAnalysisId(analysis), analysis])
        );
        for (const analysis of list) {
          map.set(getAnalysisId(analysis), analysis);
        }
        const personalizedIds = options?.personalized
          ? Array.from(
              new Set([
                ...get().personalizedIds,
                ...list.map((analysis) => getAnalysisId(analysis)),
              ])
            )
          : get().personalizedIds;
        set({
          analyses: sortByScore([...map.values()]),
          personalizedIds,
          status: "idle",
          error: null,
        });
      },
      updateAnalysis: (id, patch) =>
        set({
          analyses: get().analyses.map((analysis) =>
            getAnalysisId(analysis) === id
              ? { ...analysis, ...patch }
              : analysis
          ),
        }),
      markPersonalized: (id) => {
        if (get().personalizedIds.includes(id)) return;
        set({ personalizedIds: [...get().personalizedIds, id] });
      },
      setStatus: (status, error = null) => set({ status, error }),
      clear: () =>
        set({
          analyses: [],
          status: "idle",
          error: null,
          personalizedIds: [],
        }),
    }),
    {
      name: "inbound-sdr-copilot:leads",
      storage: createJSONStorage(() =>
        typeof window === "undefined" ? noopStorage : sessionStorage
      ),
      partialize: (state) => ({
        analyses: state.analyses,
        personalizedIds: state.personalizedIds,
      }),
    }
  )
);

const noopStorage: Storage = {
  length: 0,
  clear: () => undefined,
  getItem: () => null,
  key: () => null,
  removeItem: () => undefined,
  setItem: () => undefined,
};
