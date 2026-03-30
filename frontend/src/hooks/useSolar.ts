import { useState } from "react";
import { apiFetch } from "../utils/api";
import type { SolarResult } from "../types/index";

interface UseSolarReturn {
  result: SolarResult | null;
  loading: boolean;
  error: Error | null;
  run: (body: Record<string, unknown>) => Promise<void>;
}

export function useSolar(): UseSolarReturn {
  const [result, setResult] = useState<SolarResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  const run = async (body: Record<string, unknown>): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch("/api/v1/simulate/solar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data: SolarResult = await resp.json();
      if (!resp.ok)
        throw new Error(
          (data as unknown as { detail?: string }).detail ||
            "Solar simulation failed",
        );
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  };

  return { result, loading, error, run };
}
