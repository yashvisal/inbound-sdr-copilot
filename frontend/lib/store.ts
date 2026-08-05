"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { getAnalysisId, getLeadId } from "@/lib/api/id";
import type {
  LeadAnalysis,
  LeadInput,
  RunSource,
  StoredRun,
} from "@/lib/api/types";

/** A dashboard row: the analysis plus where it came from. */
export interface RunEntry {
  id: string;
  source: RunSource;
  created_at: string | null;
  analysis: LeadAnalysis;
}

/** A lead that has been submitted and is still being analyzed. */
export interface PendingRun {
  id: string;
  lead: LeadInput;
}

interface LeadStoreState {
  runs: RunEntry[];
  pending: PendingRun[];
  personalizedIds: string[];
  setRuns: (list: RunEntry[], options?: { personalized?: boolean }) => void;
  mergeRuns: (list: RunEntry[], options?: { personalized?: boolean }) => void;
  addPending: (leads: LeadInput[]) => string[];
  removePending: (ids: string[]) => void;
  updateAnalysis: (id: string, patch: Partial<LeadAnalysis>) => void;
  markPersonalized: (id: string) => void;
  clear: () => void;
}

function sortByScore(list: RunEntry[]): RunEntry[] {
  return [...list].sort(
    (a, b) => b.analysis.score.final_score - a.analysis.score.final_score
  );
}

/** Wrap raw analyses (e.g. a fresh live run) as dashboard entries. */
export function toRunEntries(
  analyses: LeadAnalysis[],
  source: RunSource,
  createdAt: string | null = null
): RunEntry[] {
  return analyses.map((analysis) => ({
    id: getAnalysisId(analysis),
    source,
    created_at: createdAt,
    analysis,
  }));
}

export function fromStoredRuns(runs: StoredRun[]): RunEntry[] {
  return runs.map((run) => ({
    id: run.id,
    source: run.source,
    created_at: run.created_at,
    analysis: run.analysis,
  }));
}

export const useLeadStore = create<LeadStoreState>()(
  persist(
    (set, get) => ({
      runs: [],
      pending: [],
      personalizedIds: [],
      setRuns: (list, options) =>
        set({
          runs: sortByScore(list),
          personalizedIds: options?.personalized
            ? list.map((entry) => entry.id)
            : get().personalizedIds,
        }),
      mergeRuns: (list, options) => {
        const map = new Map(get().runs.map((entry) => [entry.id, entry]));
        for (const entry of list) {
          map.set(entry.id, entry);
        }
        const personalizedIds = options?.personalized
          ? Array.from(
              new Set([
                ...get().personalizedIds,
                ...list.map((entry) => entry.id),
              ])
            )
          : get().personalizedIds;
        set({
          runs: sortByScore([...map.values()]),
          personalizedIds,
        });
      },
      addPending: (leads) => {
        const entries = leads.map((lead) => ({ id: getLeadId(lead), lead }));
        const existing = new Set(get().pending.map((item) => item.id));
        set({
          pending: [
            ...get().pending,
            ...entries.filter((entry) => !existing.has(entry.id)),
          ],
        });
        return entries.map((entry) => entry.id);
      },
      removePending: (ids) =>
        set({
          pending: get().pending.filter((item) => !ids.includes(item.id)),
        }),
      updateAnalysis: (id, patch) =>
        set({
          runs: get().runs.map((entry) =>
            entry.id === id
              ? { ...entry, analysis: { ...entry.analysis, ...patch } }
              : entry
          ),
        }),
      markPersonalized: (id) => {
        if (get().personalizedIds.includes(id)) return;
        set({ personalizedIds: [...get().personalizedIds, id] });
      },
      clear: () =>
        set({
          runs: [],
          pending: [],
          personalizedIds: [],
        }),
    }),
    {
      name: "inbound-sdr-copilot:leads",
      storage: createJSONStorage(() =>
        typeof window === "undefined" ? noopStorage : sessionStorage
      ),
      partialize: (state) => ({
        runs: state.runs,
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
