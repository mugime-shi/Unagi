import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, CheapestWindowResponse } from "../types/index";

interface UseCheapHoursReturn {
  data: CheapestWindowResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useCheapHours(
  date: string | null,
  duration: number | null,
  area: Area = "SE3",
): UseCheapHoursReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<CheapestWindowResponse>(
    date && duration ? `${date}|${duration}|${area}|${refreshKey}` : null,
    () =>
      fetchJson<CheapestWindowResponse>(
        `/api/v1/prices/cheapest-hours?date=${date}&duration=${duration}&area=${area}`,
      ),
    { clearOnLoad: true },
  );
}
