import { fetchJson, useAsyncResource } from "./useAsyncResource";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<ForecastAccuracyResponse>(
    `${area}|${days}|${refreshKey}`,
    () =>
      fetchJson<ForecastAccuracyResponse>(
        `/api/v1/prices/forecast/accuracy?area=${area}&days=${days}`,
      ),
  );
}
