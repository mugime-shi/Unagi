import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

function prevDay(iso) {
  const d = new Date(iso);
  d.setDate(d.getDate() - 1);
  return d.toISOString().split("T")[0];
}

/**
 * Fetch balancing (imbalance) prices for a given date.
 * Falls back to the previous day if today's data is not yet published
 * (ENTSO-E A85 data lags ~1–2 hours per interval; yesterday is always complete).
 *
 * Returns { data, dataDate, loading, error }
 * dataDate may differ from dateISO if a fallback was used.
 */
export function useBalancing(dateISO, area = "SE3") {
  const [data, setData] = useState(null);
  const [dataDate, setDataDate] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!dateISO) {
      setData(null);
      setDataDate(null);
      return;
    }
    setLoading(true);
    setError(null);

    const tryFetch = (d) =>
      apiFetch(`/api/v1/prices/balancing?date=${d}&area=${area}`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });

    tryFetch(dateISO)
      .then((d) => {
        setData(d);
        setDataDate(dateISO);
      })
      .catch(() => {
        // Today's data not yet published — try yesterday
        const yd = prevDay(dateISO);
        return tryFetch(yd)
          .then((d) => {
            setData(d);
            setDataDate(yd);
          })
          .catch(setError);
      })
      .finally(() => setLoading(false));
  }, [dateISO, area]);

  return { data, dataDate, loading, error };
}
