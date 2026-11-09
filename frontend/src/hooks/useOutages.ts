import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { OutagesResponse } from "../types/index";

export interface UseOutagesReturn {
  data: OutagesResponse | null;
  loading: boolean;
  error: Error | null;
}

/** Nuclear reactor status + all non-nuclear plant outages for a Stockholm date (default: today). */
export function useOutages(date?: string | null): UseOutagesReturn {
  const [data, setData] = useState<OutagesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    // min_mw=0: every plant with any reduction, so the map's plant layer can show small outages too.
    // Consumers that only want big outages must filter on nominal - available themselves.
    const qs = `?min_mw=0${date ? `&date=${date}` : ""}`;
    apiFetch(`/api/v1/generation/outages${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((json: OutagesResponse) => {
        if (!cancelled) setData(json);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [date, refreshKey]);

  return { data, loading, error };
}
