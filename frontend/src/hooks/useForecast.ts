import { fetchJson, useAsyncResource } from "./useAsyncResource";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<ForecastResponse>(
    date ? `${date}|${area}|${refreshKey}` : null,
    () =>
      fetchJson<ForecastResponse>(
        `/api/v1/prices/forecast?date=${date}&area=${area}`,
      ),
  );
}
