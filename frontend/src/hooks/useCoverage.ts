import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { Area } from "../types/index";

interface CoverageData {
  coverage_pct: number;
  calibration_error: number;
  n_samples: number;
}

interface UseCoverageReturn {
  data: CoverageData | null;
  loading: boolean;
  error: Error | null;
}

export function useCoverage(
  area: Area = "SE3",
  days: number = 30,
): UseCoverageReturn {
  const [data, setData] = useState<CoverageData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch(
      `/api/v1/prices/forecast/accuracy/coverage?area=${area}&days=${days}`,
    )
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
