import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, GridOperatorsResponse } from "../types/index";

interface UseGridOperatorsReturn {
  data: GridOperatorsResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useGridOperators(area: Area = "SE3"): UseGridOperatorsReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<GridOperatorsResponse>(`${area}|${refreshKey}`, () =>
    fetchJson<GridOperatorsResponse>(`/api/v1/grid-operators?area=${area}`),
  );
}
