import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { useRefresh } from "./useRefresh";
import type { GenerationPoint, GenerationResponse } from "../types/index";

const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const ZONES = ["SE1", "SE2", "SE3", "SE4"] as const;

export interface NationalGenerationData {
  time_series: GenerationPoint[];
  renewable_pct: number | null;
  carbon_free_pct: number | null;
  carbon_intensity: number | null;
  latest_slot: string | null;
  zones_included: string[];
  zones_missing: string[];
}

interface UseNationalGenerationReturn {
  data: NationalGenerationData | null;
  loading: boolean;
  error: Error | null;
}

function aggregateTimeSeries(
  zoneData: { zone: string; resp: GenerationResponse | null }[],
): GenerationPoint[] {
  const byTimestamp = new Map<string, GenerationPoint>();
  for (const { resp } of zoneData) {
    if (!resp?.time_series) continue;
    for (const pt of resp.time_series) {
      const existing = byTimestamp.get(pt.timestamp_utc);
      if (!existing) {
        byTimestamp.set(pt.timestamp_utc, {
          timestamp_utc: pt.timestamp_utc,
          total_mw: pt.total_mw ?? 0,
          hydro: pt.hydro ?? 0,
          wind: pt.wind ?? 0,
          nuclear: pt.nuclear ?? 0,
          solar: pt.solar ?? 0,
          other: pt.other ?? 0,
          fossil: pt.fossil ?? 0,
        });
      } else {
        existing.total_mw = (existing.total_mw ?? 0) + (pt.total_mw ?? 0);
        existing.hydro = (existing.hydro ?? 0) + (pt.hydro ?? 0);
        existing.wind = (existing.wind ?? 0) + (pt.wind ?? 0);
        existing.nuclear = (existing.nuclear ?? 0) + (pt.nuclear ?? 0);
        existing.solar = (existing.solar ?? 0) + (pt.solar ?? 0);
        existing.other = (existing.other ?? 0) + (pt.other ?? 0);
        existing.fossil = (existing.fossil ?? 0) + (pt.fossil ?? 0);
      }
    }
  }

  // Recompute renewable/carbon_free/carbon_intensity per aggregated point
  const points = Array.from(byTimestamp.values()).sort((a, b) =>
    a.timestamp_utc.localeCompare(b.timestamp_utc),
  );
  for (const pt of points) {
    const renewable = (pt.hydro ?? 0) + (pt.wind ?? 0) + (pt.solar ?? 0);
    const carbonFree = renewable + (pt.nuclear ?? 0);
    const total = (pt.total_mw ?? 0) || 1;
    pt.renewable_pct = Math.round((renewable / total) * 100);
    // Approximate carbon intensity: fossil = ~400gCO2, other = 20, renewable/nuclear = 0
    const co2 = (pt.fossil ?? 0) * 400 + (pt.other ?? 0) * 20;
    pt.carbon_intensity = total > 0 ? co2 / total : 0;
    void carbonFree;
  }
  return points;
}

export function useNationalGeneration(
  mode: "today" | "24h" = "24h",
): UseNationalGenerationReturn {
  const [data, setData] = useState<NationalGenerationData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const { key: refreshKey } = useRefresh();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    // For 24h mode: fetch today + yesterday, then trim to 24h window
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const yesterdayStr = yesterday.toISOString().split("T")[0];

    const fetches = ZONES.flatMap((zone) => {
      const todayFetch = apiFetch(`${API_BASE}/generation/today?area=${zone}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((json) => ({ zone, resp: json as GenerationResponse | null }))
        .catch(() => ({ zone, resp: null as GenerationResponse | null }));

      if (mode !== "24h") return [todayFetch];

      const yesterdayFetch = apiFetch(
        `${API_BASE}/generation/date?date=${yesterdayStr}&area=${zone}`,
      )
        .then((r) => (r.ok ? r.json() : null))
        .then((json) => ({ zone, resp: json as GenerationResponse | null }))
        .catch(() => ({ zone, resp: null as GenerationResponse | null }));

      return [todayFetch, yesterdayFetch];
    });

    Promise.all(fetches)
      .then((raw) => {
        // Merge same-zone results
        const merged = new Map<string, GenerationResponse>();
        for (const { zone, resp } of raw) {
          if (!resp?.time_series?.length) continue;
          const existing = merged.get(zone);
          if (!existing) {
            merged.set(zone, resp);
          } else {
            // Append, dedup by timestamp
            const seen = new Set(
              existing.time_series.map((p) => p.timestamp_utc),
            );
            for (const pt of resp.time_series) {
              if (!seen.has(pt.timestamp_utc)) {
                existing.time_series.push(pt);
              }
            }
          }
        }

        // 24h mode: don't filter here — let the chart take the last 24 hours

        const results = Array.from(merged.entries()).map(([zone, resp]) => ({
          zone,
          resp,
        }));
        return results;
      })
      .then((results) => {
        if (cancelled) return;
        const zonesIncluded = results
          .filter((r) => r.resp?.time_series?.length)
          .map((r) => r.zone);
        const zonesMissing = ZONES.filter((z) => !zonesIncluded.includes(z));

        if (zonesIncluded.length === 0) {
          setError(new Error("No generation data available"));
          setLoading(false);
          return;
        }

        const time_series = aggregateTimeSeries(results);

        // Compute national totals from the latest point
        const latest = time_series[time_series.length - 1];
        let renewable_pct: number | null = null;
        let carbon_free_pct: number | null = null;
        let carbon_intensity: number | null = null;
        let latest_slot: string | null = null;

        if (latest) {
          const total = latest.total_mw ?? 0;
          const renewable =
            (latest.hydro ?? 0) + (latest.wind ?? 0) + (latest.solar ?? 0);
          const carbonFree = renewable + (latest.nuclear ?? 0);
          if (total > 0) {
            renewable_pct = Math.round((renewable / total) * 100);
            carbon_free_pct = Math.round((carbonFree / total) * 100);
            const co2 = (latest.fossil ?? 0) * 400 + (latest.other ?? 0) * 20;
            carbon_intensity = Math.round(co2 / total);
          }
          latest_slot = latest.timestamp_utc;
        }

        setData({
          time_series,
          renewable_pct,
          carbon_free_pct,
          carbon_intensity,
          latest_slot,
          zones_included: zonesIncluded,
          zones_missing: zonesMissing,
        });
        setLoading(false);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [mode, refreshKey]);

  return { data, loading, error };
}
