import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { WindForecastSummaryResponse } from "../types/index";

interface UseWindForecastSummaryReturn {
  data: WindForecastSummaryResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useWindForecastSummary(
  hours: number = 24,
): UseWindForecastSummaryReturn {
  const [data, setData] = useState<WindForecastSummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/weather/wind-forecast-summary?hours=${hours}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [hours, refreshKey]);

  return { data, loading, error };
}
