import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
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
  }, [days]);

  return { data, loading, error };
}
