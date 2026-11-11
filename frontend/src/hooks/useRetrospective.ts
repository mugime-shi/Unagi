import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, RetrospectiveResponse } from "../types/index";

interface UseRetrospectiveReturn {
  data: RetrospectiveResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useRetrospective(
  date: string | null,
  area: Area = "SE3",
): UseRetrospectiveReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<RetrospectiveResponse>(
    date ? `${date}|${area}|${refreshKey}` : null,
    () =>
      fetchJson<RetrospectiveResponse>(
        `/api/v1/prices/forecast/retrospective?date=${date}&area=${area}`,
      ),
  );
}
