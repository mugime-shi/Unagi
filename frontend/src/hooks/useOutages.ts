import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { OutagesResponse } from "../types/index";

export interface UseOutagesReturn {
  data: OutagesResponse | null;
  loading: boolean;
  error: Error | null;
}

/** Nuclear reactor status + all non-nuclear plant outages for a Stockholm date (default: today). */
export function useOutages(date?: string | null): UseOutagesReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<OutagesResponse>(
    `${date ?? ""}|${refreshKey}`,
    () => {
      // min_mw=0: every plant with any reduction, so the map's plant layer can show small outages too.
      // Consumers that only want big outages must filter on nominal - available themselves.
      const qs = `?min_mw=0${date ? `&date=${date}` : ""}`;
      return fetchJson<OutagesResponse>(`/api/v1/generation/outages${qs}`);
    },
  );
}
