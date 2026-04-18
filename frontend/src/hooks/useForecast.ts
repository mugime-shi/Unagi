import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { Area, ForecastResponse } from "../types/index";

interface UseForecastReturn {
  data: ForecastResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useForecast(
  date: string | null,
  area: Area = "SE3",
): UseForecastReturn {
  const [data, setData] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    if (!date) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/forecast?date=${date}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [date, area, refreshKey]);

  return { data, loading, error };
}
