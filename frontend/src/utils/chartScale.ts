import type { ChartDataPoint } from "../types/index";

/**
 * Y-axis smart scaling: clip at 95th percentile to prevent spikes
 * from compressing the normal price range.
 */

interface Spike {
  hour: string;
  value: number;
  key: string;
}

interface ClippedDomainResult {
  domain: [number, number | "auto"];
  spikes: Spike[];
}

function percentile(sorted: number[], p: number): number {
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

/**
 * @param data   – chartData array
 * @param keys   – dataKeys to consider (e.g. ['price_sek_kwh', 'lgbm_forecast'])
 * @returns clipped domain and spike data points
 */
export function computeClippedDomain(
  data: ChartDataPoint[],
  keys: (keyof ChartDataPoint)[],
): ClippedDomainResult {
  const values: number[] = [];
  for (const d of data) {
    for (const k of keys) {
      const v = d[k];
      if (v != null && typeof v === "number" && isFinite(v)) values.push(v);
    }
  }

  if (values.length === 0) return { domain: [0, "auto"], spikes: [] };

  values.sort((a, b) => a - b);
  const actualMax = values[values.length - 1];
  const actualMin = Math.min(0, values[0]);
  const p95 = percentile(values, 95);
  const clippedMax = p95 * 1.1;

  // Only clip if the spike is significantly above the 95th percentile
  if (actualMax <= clippedMax) {
    return { domain: [actualMin, actualMax], spikes: [] };
  }

  // Find spike data points that exceed the clipped max
  const spikes: Spike[] = [];
  for (const d of data) {
    for (const k of keys) {
      const v = d[k];
      if (v != null && typeof v === "number" && v > clippedMax) {
        spikes.push({ hour: d.hour, value: v, key: k as string });
      }
    }
  }

  return { domain: [actualMin, clippedMax], spikes };
}
