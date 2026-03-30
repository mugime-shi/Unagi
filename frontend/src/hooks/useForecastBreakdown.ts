import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, ForecastBreakdownResponse } from "../types/index";

interface UseForecastBreakdownReturn {
  data: ForecastBreakdownResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useForecastBreakdown(
  area: Area = "SE3",
  days: number = 30,
  by: string = "hour",
): UseForecastBreakdownReturn {
  const [data, setData] = useState<ForecastBreakdownResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(
      `/api/v1/prices/forecast/accuracy/breakdown?area=${area}&days=${days}&by=${by}`,
    )
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [area, days, by]);

  return { data, loading, error };
}
