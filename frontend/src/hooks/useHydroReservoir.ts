import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { HydroReservoirResponse } from "../types/index";

interface UseHydroReservoirReturn {
  data: HydroReservoirResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useHydroReservoir(): UseHydroReservoirReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<HydroReservoirResponse>(`${refreshKey}`, () =>
    fetchJson<HydroReservoirResponse>("/api/v1/generation/hydro-reservoir"),
  );
}
