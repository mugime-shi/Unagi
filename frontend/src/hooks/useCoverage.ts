import { fetchJson, useAsyncResource } from "./useAsyncResource";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<CoverageData>(`${area}|${days}|${refreshKey}`, () =>
    fetchJson<CoverageData>(
      `/api/v1/prices/forecast/accuracy/coverage?area=${area}&days=${days}`,
    ),
  );
}
