"use client";

import { toast } from "sonner";

import { useLeadStore, type RunEntry } from "@/lib/store";

/**
 * Announce finished analyses. Rank is read from the store after the merge, so
 * it reflects the lead's real position in the score-sorted dashboard.
 */
export function announceCompletedRuns(entries: RunEntry[]) {
  const runs = useLeadStore.getState().runs;

  for (const entry of entries) {
    const rank = runs.findIndex((run) => run.id === entry.id) + 1;
    const { lead, score } = entry.analysis;
    toast.success(`${lead.name} scored ${score.final_score}`, {
      description:
        `${score.priority} priority` +
        (rank > 0 ? ` · rank #${rank} of ${runs.length}` : ""),
    });
  }
}
