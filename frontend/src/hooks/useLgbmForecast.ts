import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, LgbmForecastResponse } from "../types/index";

interface UseLgbmForecastReturn {
  data: LgbmForecastResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useLgbmForecast(
  date: string | null,
  area: Area = "SE3",
): UseLgbmForecastReturn {
  const [data, setData] = useState<LgbmForecastResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!date) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast?date=${date}&area=${area}&model=lgbm`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [date, area]);

  return { data, loading, error };
}
