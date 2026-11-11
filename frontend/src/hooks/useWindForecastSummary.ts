import { fetchJson, useAsyncResource } from "./useAsyncResource";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<WindForecastSummaryResponse>(
    `${hours}|${refreshKey}`,
    () =>
      fetchJson<WindForecastSummaryResponse>(
        `/api/v1/weather/wind-forecast-summary?hours=${hours}`,
      ),
  );
}
