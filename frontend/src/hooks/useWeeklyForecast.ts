import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<WeeklyClassifiedResponse>(
    enabled ? `${area}|${refreshKey}` : null,
    () =>
      fetchJson<WeeklyClassifiedResponse>(
        `/api/v1/prices/forecast/weekly?area=${area}`,
      ),
  );
}
