import { useEffect, useEffectEvent, useState } from "react";
import { apiFetch } from "../utils/api";

interface Settled<T> {
  key: string | null;
  data: T | null;
  error: Error | null;
}

const EMPTY: Settled<never> = { key: null, data: null, error: null };

/** Thrown by a fetcher to report an error AND drop the previously shown data. */
export class ClearDataError extends Error {}

export async function fetchJson<T>(url: string): Promise<T> {
  const r = await apiFetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

interface Options {
  /** Hide the previous data while a new request is in flight. */
  clearOnLoad?: boolean;
}

/**
 * Shared fetch state for the data hooks.
 *
 * `key` identifies the request (include the refresh key). `null` means "do not
 * fetch": no data, not loading. Results are stored with the key they answer,
 * so `loading` is derived (key !== settled key) and setState only ever runs in
 * async callbacks. Like the hand-rolled hooks this replaces, the previous data
 * stays visible while a refetch is in flight; a late response for an outdated
 * key is dropped.
 */
export function useAsyncResource<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  { clearOnLoad = false }: Options = {},
): { data: T | null; loading: boolean; error: Error | null } {
  const [state, setState] = useState<Settled<T>>(EMPTY);

  // Adjust-state-during-render: entering the "no request" state forgets old data.
  if (key === null && (state.data !== null || state.error !== null)) {
    setState(EMPTY);
  }

  const run = useEffectEvent(fetcher);

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    run().then(
      (data) => {
        if (!cancelled) setState({ key, data, error: null });
      },
      (err: unknown) => {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setState((prev) => ({
          key,
          data: error instanceof ClearDataError ? null : prev.data,
          error,
        }));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key]);

  const loading = key !== null && state.key !== key;
  return {
    data: key === null || (clearOnLoad && loading) ? null : state.data,
    loading,
    error: key !== null && state.key === key ? state.error : null,
  };
}
