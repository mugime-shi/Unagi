import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, HistoryResponse } from "../types/index";

interface UseHistoryReturn {
  data: HistoryResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useHistory(
  days: number = 90,
  area: Area = "SE3",
): UseHistoryReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<HistoryResponse>(
    `${days}|${area}|${refreshKey}`,
    () =>
      fetchJson<HistoryResponse>(
        `/api/v1/prices/history?days=${days}&area=${area}`,
      ),
  );
}
