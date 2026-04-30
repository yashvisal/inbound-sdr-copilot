"use client"

import { useSyncExternalStore } from "react"

import { useLeadStore } from "@/lib/store"

export function useHasHydrated(): boolean {
  return useSyncExternalStore(
    (callback) => useLeadStore.persist.onFinishHydration(callback),
    () => useLeadStore.persist.hasHydrated(),
    () => false
  )
}
