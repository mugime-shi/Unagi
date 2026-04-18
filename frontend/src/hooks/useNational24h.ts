import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";

export interface National24hEntry {
  timestamp_utc: string;
  hour_label: string;
  hydro: number;
  nuclear: number;
  wind: number;
  solar: number;
  fossil: number;
  other: number;
  total_mw: number;
  renewable_pct: number | null;
}

export interface National24hResponse {
  count: number;
  latest_slot: string | null;
  renewable_pct: number | null;
  carbon_free_pct: number | null;
  hourly: National24hEntry[];
}

interface UseNational24hReturn {
  data: National24hResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useNational24h(): UseNational24hReturn {
  const [data, setData] = useState<National24hResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch("/api/v1/generation/national-24h")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [refreshKey]);

  return { data, loading, error };
}
