import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { Area, ForecastAccuracyResponse } from "../types/index";

interface UseForecastAccuracyReturn {
  data: ForecastAccuracyResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useForecastAccuracy(
  area: Area = "SE3",
  days: number = 30,
): UseForecastAccuracyReturn {
  const [data, setData] = useState<ForecastAccuracyResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast/accuracy?area=${area}&days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [area, days, refreshKey]);

  return { data, loading, error };
}
