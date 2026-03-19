import { useState } from "react";
import { apiFetch } from "../utils/api";

export function useSimulate() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async (body) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch("/api/v1/simulate/consumption", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Simulation failed");
      setResult(data);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  };

  return { result, loading, error, run };
}
