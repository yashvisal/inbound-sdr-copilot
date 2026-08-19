"use client";

import * as React from "react";

import { fetchQuota } from "@/lib/api/client";

interface QuotaState {
  loaded: boolean;
  enabled: boolean;
  runs_remaining: number;
  runs_limit: number;
  /** Leads one visitor may analyze per day; also caps CSV upload size. */
  perVisitorDailyLimit: number;
}

const DEFAULT_DAILY_LIMIT = 3;

const INITIAL: QuotaState = {
  loaded: false,
  enabled: false,
  runs_remaining: 0,
  runs_limit: 0,
  perVisitorDailyLimit: DEFAULT_DAILY_LIMIT,
};

/**
 * Last known quota. Held in a module variable for client navigations and
 * mirrored to sessionStorage so a full page refresh also paints the meter
 * immediately; either way the fetch still runs to revalidate.
 */
const CACHE_KEY = "inbound-sdr-copilot:quota";

let cached: QuotaState | null = null;

function readCache(): QuotaState | null {
  if (cached) return cached;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(CACHE_KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<QuotaState>) : null;
    // A hand-edited or half-written entry would otherwise render "NaN/NaN".
    cached =
      parsed &&
      typeof parsed.runs_remaining === "number" &&
      typeof parsed.runs_limit === "number"
        ? (parsed as QuotaState)
        : null;
  } catch {
    cached = null;
  }
  return cached;
}

function writeCache(next: QuotaState) {
  cached = next;
  try {
    window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(next));
  } catch {
    // Private mode or storage full: the module variable still works.
  }
}

/**
 * Live-run budget for the public demo. `refresh` is called after a run
 * finishes so the remaining count updates without a page reload.
 */
export function useQuota(): QuotaState & { refresh: () => void } {
  // Starts at INITIAL so the server and client first render agree; the cached
  // value is applied on mount, before the network round trip resolves.
  const [state, setState] = React.useState<QuotaState>(INITIAL);

  const load = React.useCallback(async () => {
    // On a cold refresh there is no cache and the backend function may still
    // be waking up, so the first request can fail or time out. Retry a couple
    // of times before giving up; otherwise the meter never appears until the
    // next full reload.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const quota = await fetchQuota();
        const next: QuotaState = {
          loaded: true,
          enabled: quota.enabled,
          runs_remaining: quota.runs_remaining,
          runs_limit: quota.runs_limit,
          perVisitorDailyLimit:
            quota.per_visitor_daily_limit || DEFAULT_DAILY_LIMIT,
        };
        writeCache(next);
        setState(next);
        return;
      } catch {
        if (readCache()) break;
        await new Promise((resolve) => setTimeout(resolve, 1500 * (attempt + 1)));
      }
    }
    // Quota unknown (backend unreachable): leave the UI unrestricted.
    const next = { ...(readCache() ?? INITIAL), loaded: true };
    writeCache(next);
    setState(next);
  }, []);

  React.useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const restored = readCache();
      if (restored) setState(restored);
      void load();
    });
    return () => cancelAnimationFrame(frame);
  }, [load]);

  return { ...state, refresh: () => void load() };
}
