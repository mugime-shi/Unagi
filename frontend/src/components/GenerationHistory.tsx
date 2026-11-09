import { useMemo } from "react";
import { useChartColors } from "../hooks/useChartColors";
import { useGenerationHistory } from "../hooks/useGenerationHistory";
import { useIsMobile } from "../hooks/useIsMobile";
import { granularityLabel } from "../utils/bucket";
import { historyToRows } from "../utils/genHistory";
import { GenChart } from "./GenChart";

/** National (SE1–SE4) generation mix history for the Trends page. */
export function GenerationHistory({ days }: { days: number }) {
  const cc = useChartColors();
  const isMobile = useIsMobile();
  const { data, loading, error } = useGenerationHistory(days);

  const rows = useMemo(
    () => (data?.daily?.length ? historyToRows(data.daily, days) : []),
    [data, days],
  );

  if (loading && !data)
    return <p className="text-content-muted text-sm">Loading generation...</p>;
  if (error)
    return (
      <p className="text-red-500 text-sm">
        Failed to load generation: {error.message}
      </p>
    );

  return (
    <div className="bg-surface-primary rounded-2xl p-4">
      <h2 className="text-base font-medium text-content-primary mb-1">
        Generation mix
        <span className="text-content-muted ml-1.5 font-normal">
          MW, {granularityLabel(days)} avg, all of Sweden (SE1–SE4)
        </span>
      </h2>
      {rows.length > 0 ? (
        <GenChart data={rows} cc={cc} isMobile={isMobile} />
      ) : (
        <p className="text-sm text-content-muted text-center py-16">
          No generation data available
        </p>
      )}
    </div>
  );
}
