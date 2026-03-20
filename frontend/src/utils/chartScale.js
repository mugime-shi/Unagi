/**
 * Y-axis smart scaling: clip at 95th percentile to prevent spikes
 * from compressing the normal price range.
 */

function percentile(sorted, p) {
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

/**
 * @param {Array<Object>} data   – chartData array
 * @param {string[]}      keys   – dataKeys to consider (e.g. ['price_sek_kwh', 'lgbm_forecast'])
 * @returns {{ domain: [number, number], spikes: Array<{ hour: string, value: number, key: string }> }}
 */
export function computeClippedDomain(data, keys) {
  const values = [];
  for (const d of data) {
    for (const k of keys) {
      if (d[k] != null && isFinite(d[k])) values.push(d[k]);
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
  const spikes = [];
  for (const d of data) {
    for (const k of keys) {
      if (d[k] != null && d[k] > clippedMax) {
        spikes.push({ hour: d.hour, value: d[k], key: k });
      }
    }
  }

  return { domain: [actualMin, clippedMax], spikes };
}
