import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { StoryResponse } from "../types/index";

interface UseStoryReturn {
  data: StoryResponse | null;
  loading: boolean;
  error: Error | null;
}

export function useStory(): UseStoryReturn {
  const [data, setData] = useState<StoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiFetch("/api/v1/story/today")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [refreshKey]);

  return { data, loading, error };
}
