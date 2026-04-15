import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

export interface GenHistoryDay {
  date: string;
  hydro: number;
  nuclear: number;
  wind: number;
  solar: number;
  fossil: number;
  other: number;
  total_mw: number;
  renewable_pct: number | null;
}

export interface GenHistoryResponse {
  days: number;
  start: string;
  end: string;
  daily: GenHistoryDay[];
}

interface UseGenerationHistoryReturn {
  data: GenHistoryResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useGenerationHistory(
  days: number = 7,
): UseGenerationHistoryReturn {
  const [data, setData] = useState<GenHistoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (days < 1) {
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/generation/history?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [days]);

  return { data, loading, error };
}
