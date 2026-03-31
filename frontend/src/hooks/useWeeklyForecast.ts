import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, WeeklyClassifiedResponse } from "../types/index";

interface UseWeeklyForecastReturn {
  data: WeeklyClassifiedResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useWeeklyForecast(
  area: Area = "SE3",
  enabled: boolean = true,
): UseWeeklyForecastReturn {
  const [data, setData] = useState<WeeklyClassifiedResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast/weekly?area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [area, enabled]);

  return { data, loading, error };
}
