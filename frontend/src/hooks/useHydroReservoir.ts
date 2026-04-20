import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { HydroReservoirResponse } from "../types/index";

interface UseHydroReservoirReturn {
  data: HydroReservoirResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useHydroReservoir(): UseHydroReservoirReturn {
  const [data, setData] = useState<HydroReservoirResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch("/api/v1/generation/hydro-reservoir")
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
