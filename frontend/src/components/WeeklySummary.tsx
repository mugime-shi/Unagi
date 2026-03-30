import { useWeeklyForecast } from "../hooks/useWeeklyForecast";
import type { Area, WeeklyDayClassified } from "../types/index";

interface ClassConfig {
  color: string;
  bg: string;
  dot: string;
}

const CLASS_CONFIG: Record<WeeklyDayClassified["classification"], ClassConfig> =
  {
    cheap: {
      color: "text-cyan-300",
      bg: "bg-cyan-950/40 border-cyan-800/40",
      dot: "bg-cyan-400",
    },
    normal: {
      color: "text-gray-200",
      bg: "bg-sea-800/50 border-sea-700/40",
      dot: "bg-gray-400",
    },
    expensive: {
      color: "text-orange-300",
      bg: "bg-orange-950/40 border-orange-800/40",
      dot: "bg-orange-400",
    },
  };

const SHORT_WEEKDAYS: Record<string, string> = {
  Monday: "Mon",
  Tuesday: "Tue",
  Wednesday: "Wed",
  Thursday: "Thu",
  Friday: "Fri",
  Saturday: "Sat",
  Sunday: "Sun",
};

interface WeeklySummaryProps {
  area?: Area;
  onDateSelect?: (date: string) => void;
}

export function WeeklySummary({
  area = "SE3",
  onDateSelect,
}: WeeklySummaryProps) {
  const { data, loading, error } = useWeeklyForecast(area);

  if (loading) {
    return (
      <div className="no-scrollbar flex gap-2 overflow-x-auto snap-x snap-mandatory pb-2 sm:grid sm:grid-cols-7 sm:gap-1.5 sm:overflow-visible sm:pb-0">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="min-w-[5.5rem] sm:min-w-0 h-28 rounded-xl border border-sea-700/30 bg-sea-900/30 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (error || !data?.days?.length) return null;

  const refAvg = data.reference_avg_30d;

  return (
    <div className="space-y-2">
      {/* Header with color legend */}
      <div className="flex items-center justify-between flex-wrap gap-1">
        <h3 className="text-sm font-medium text-gray-400">Weekly forecast</h3>
        <div className="flex items-center gap-3 text-[0.6rem] text-gray-500">
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-cyan-400" />
            Cheap
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-gray-400" />
            Normal
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-orange-400" />
            Expensive
          </span>
          {refAvg && (
            <span className="hidden sm:inline text-gray-600">
              vs 30d avg {refAvg.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* Cards */}
      <div className="no-scrollbar flex gap-2 overflow-x-auto snap-x snap-mandatory pb-2 sm:grid sm:grid-cols-7 sm:gap-1.5 sm:overflow-visible sm:pb-0">
        {data.days.map((day) => {
          const cfg = CLASS_CONFIG[day.classification] || CLASS_CONFIG.normal;
          const isTomorrow = day.horizon === 1;
          const pctDiff = refAvg
            ? Math.round(((day.daily_avg - refAvg) / refAvg) * 100)
            : null;
          const d = new Date(day.date + "T12:00:00");
          const shortDate = d.toLocaleDateString("en-GB", {
            day: "numeric",
            month: "short",
          });
          const conf = Math.round(day.confidence * 100);

          return (
            <div
              key={day.date}
              onClick={() => onDateSelect?.(day.date)}
              className={`min-w-[5.5rem] snap-center sm:min-w-0 rounded-xl border px-1.5 py-3 text-center ${cfg.bg} ${
                isTomorrow ? "ring-1 ring-amber-500/30" : ""
              } ${onDateSelect ? "cursor-pointer hover:brightness-110 transition-all" : ""}`}
            >
              <p className="text-[0.65rem] text-gray-500 truncate">
                {SHORT_WEEKDAYS[day.weekday] || day.weekday} {shortDate}
              </p>
              <p className={`text-xl sm:text-2xl font-bold ${cfg.color} mt-1`}>
                {day.daily_avg.toFixed(2)}
              </p>
              <p className="text-[0.55rem] text-gray-600">SEK/kWh</p>
              {pctDiff !== null && (
                <p
                  className={`text-xs mt-1 font-medium ${pctDiff < 0 ? "text-cyan-400" : pctDiff > 0 ? "text-orange-400" : "text-gray-400"}`}
                >
                  {pctDiff < 0 ? "\u2193" : pctDiff > 0 ? "\u2191" : ""}
                  {Math.abs(pctDiff)}%
                </p>
              )}
              <p className="text-[0.6rem] text-gray-600 mt-1">conf. {conf}%</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
