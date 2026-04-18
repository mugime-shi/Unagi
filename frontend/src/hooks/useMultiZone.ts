import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { MultiZoneResponse } from "../types/index";

interface UseMultiZoneReturn {
  data: MultiZoneResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useMultiZone(days: number = 90): UseMultiZoneReturn {
  const [data, setData] = useState<MultiZoneResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/multi-zone?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [days, refreshKey]);

  return { data, loading, error };
}
