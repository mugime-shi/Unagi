import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { Area, HistoryResponse } from "../types/index";

interface UseHistoryReturn {
  data: HistoryResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useHistory(
  days: number = 90,
  area: Area = "SE3",
): UseHistoryReturn {
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/history?days=${days}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [days, area, refreshKey]);

  return { data, loading, error };
}
