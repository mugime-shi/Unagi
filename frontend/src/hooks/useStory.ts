import { fetchJson, useAsyncResource } from "./useAsyncResource";
import { useRefresh } from "./useRefresh";
import type { StoryResponse } from "../types/index";

interface UseStoryReturn {
  data: StoryResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useStory(): UseStoryReturn {
  const { key: refreshKey } = useRefresh();
  return useAsyncResource<StoryResponse>(`${refreshKey}`, () =>
    fetchJson<StoryResponse>("/api/v1/story/today"),
  );
}
