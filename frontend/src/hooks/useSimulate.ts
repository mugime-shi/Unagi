import { useState } from "react";
import { apiFetch } from "../utils/api";
import type { SimulationResponse } from "../types/index";

interface UseSimulateReturn {
  result: SimulationResponse | null;
  loading: boolean;
  error: Error | null;
  run: (body: Record<string, unknown>) => Promise<void>;
}

export function useSimulate(): UseSimulateReturn {
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  const run = async (body: Record<string, unknown>): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch("/api/v1/simulate/consumption", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data: SimulationResponse = await resp.json();
      if (!resp.ok)
        throw new Error(
          (data as unknown as { detail?: string }).detail ||
            "Simulation failed",
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
