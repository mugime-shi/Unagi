import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { Area, GenerationResponse } from "../types/index";

const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

interface UseGenerationReturn {
  data: GenerationResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useGeneration(area: Area = "SE3"): UseGenerationReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<GenerationResponse>(`${area}|${refreshKey}`, () =>
    fetchJson<GenerationResponse>(`${API_BASE}/generation/today?area=${area}`),
  );
}
