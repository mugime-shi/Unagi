import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, ElhandlareResponse } from "../types/index";

interface UseElhandlareReturn {
  data: ElhandlareResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useElhandlare(area: Area = "SE3"): UseElhandlareReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<ElhandlareResponse>(`${area}|${refreshKey}`, () =>
    fetchJson<ElhandlareResponse>(`/api/v1/elhandlare?area=${area}`),
  );
}
