import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<ForecastBreakdownResponse>(
    `${area}|${days}|${by}|${refreshKey}`,
    () =>
      fetchJson<ForecastBreakdownResponse>(
        `/api/v1/prices/forecast/accuracy/breakdown?area=${area}&days=${days}&by=${by}`,
      ),
  );
}
