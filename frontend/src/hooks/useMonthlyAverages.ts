import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
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
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<MonthlyAvgResponse>(
    `${months}|${area}|${refreshKey}`,
    () =>
      fetchJson<MonthlyAvgResponse>(
        `/api/v1/prices/monthly-averages?months=${months}&area=${area}`,
      ),
  );
}
