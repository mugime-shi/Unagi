import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { Area, MonthlyAvgResponse } from "../types/index";

interface UseMonthlyAveragesReturn {
  data: MonthlyAvgResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useMonthlyAverages(
  months: number = 12,
  area: Area = "SE3",
): UseMonthlyAveragesReturn {
  const [data, setData] = useState<MonthlyAvgResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(`/api/v1/prices/monthly-averages?months=${months}&area=${area}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [months, area]);

  return { data, loading, error };
}
