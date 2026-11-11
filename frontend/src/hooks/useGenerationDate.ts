import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, GenerationResponse } from "../types/index";

const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

interface UseGenerationDateReturn {
  data: GenerationResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useGenerationDate(
  date: string | null,
  area: Area = "SE3",
): UseGenerationDateReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<GenerationResponse>(
    date ? `${date}|${area}|${refreshKey}` : null,
    () =>
      fetchJson<GenerationResponse>(
        `${API_BASE}/generation/date?date=${date}&area=${area}`,
      ),
  );
}
