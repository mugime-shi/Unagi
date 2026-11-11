import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { MultiZoneResponse } from "../types/index";

interface UseMultiZoneReturn {
  data: MultiZoneResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useMultiZone(days: number = 90): UseMultiZoneReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<MultiZoneResponse>(`${days}|${refreshKey}`, () =>
    fetchJson<MultiZoneResponse>(`/api/v1/prices/multi-zone?days=${days}`),
  );
}
