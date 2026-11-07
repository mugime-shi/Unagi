import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { OutagesResponse } from "../types/index";

interface UseOutagesReturn {
  data: OutagesResponse | null;
  loading: boolean;
  error: Error | null;
}

/** Nuclear reactor status + large outages for a Stockholm date (default: today). */
export function useOutages(date?: string | null): UseOutagesReturn {
  const [data, setData] = useState<OutagesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const qs = date ? `?date=${date}` : "";
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
