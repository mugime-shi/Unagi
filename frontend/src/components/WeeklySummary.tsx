import { formatPrice } from "../utils/formatters";
import type {
  Area,
  WeeklyClassifiedResponse,
  WeeklyDayClassified,
} from "../types/index";

interface ClassConfig {
  color: string;
  bg: string;
  dot: string;
}

const CLASS_CONFIG: Record<WeeklyDayClassified["classification"], ClassConfig> =
  {
    cheap: {
      color: "text-cyan-600 dark:text-cyan-300",
      bg: "bg-[var(--indicator-cheap-bg)] border-[var(--indicator-cheap-border)]",
      dot: "bg-cyan-400",
    },
    normal: {
      color: "text-content-primary",
      bg: "bg-[var(--indicator-normal-bg)] border-[var(--indicator-normal-border)]",
      dot: "bg-gray-400",
    },
    expensive: {
      color: "text-orange-600 dark:text-orange-300",
      bg: "bg-[var(--indicator-expensive-bg)] border-[var(--indicator-expensive-border)]",
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

const AREAS: Area[] = ["SE1", "SE2", "SE3", "SE4"];

interface WeeklySummaryProps {
  area?: Area;
  /**
   * When provided, renders an SE1–SE4 selector in the header and calls this on
   * change. Omit it (e.g. the Tomorrow tab, which has its own area control) to
   * hide the selector.
   */
  onAreaChange?: (area: Area) => void;
  data: WeeklyClassifiedResponse | null;
  loading: boolean;
  onDateSelect?: (date: string) => void;
  /**
   * Include tomorrow's card. The Tomorrow tab hides it (it is shown in the
   * main chart there); on Overview there is no such chart, so show all 7 days.
   */
  includeTomorrow?: boolean;
}

export function WeeklySummary({
  area,
  onAreaChange,
  data,
  loading,
  onDateSelect,
  includeTomorrow = false,
}: WeeklySummaryProps) {
  const refAvg = data?.reference_avg_30d ?? null;

  // Header stays mounted across states so the area pills don't flicker while a
  // switch is loading (the hook keeps loading=true until the new area arrives).
  const header = (
    <div className="flex items-center justify-between flex-wrap gap-1">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-sm font-medium text-content-secondary">
          Weekly forecast{" "}
          <span className="text-xs font-normal text-content-faint">
            · daily avg
          </span>
        </h3>
        {onAreaChange && area && (
          <div className="flex gap-1" role="group" aria-label="Forecast area">
            {AREAS.map((a) => (
              <button
                key={a}
                onClick={() => onAreaChange(a)}
                aria-pressed={a === area}
                className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors ${
                  a === area
                    ? "bg-sky-600 text-white"
                    : "bg-surface-secondary text-content-secondary hover:bg-surface-tertiary"
                }`}
              >
                {a}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 text-xs text-content-muted">
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
          <span className="hidden sm:inline text-content-faint">
            vs 30d avg {formatPrice(refAvg)}
          </span>
        )}
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="space-y-2">
        {header}
        <div className="no-scrollbar flex gap-2 overflow-x-auto snap-x snap-mandatory pb-2 sm:grid sm:grid-cols-7 sm:gap-1.5 sm:overflow-visible sm:pb-0">
          {Array.from({ length: 7 }).map((_, i) => (
            <div
              key={i}
              className="min-w-[5.5rem] sm:min-w-0 h-28 rounded-xl border border-surface-tertiary/30 bg-surface-primary/30 animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  if (!data?.days?.length) return null;

  return (
    <div className="space-y-2">
      {header}

      {/* Cards — skip tomorrow unless includeTomorrow (it's shown in the
          Tomorrow tab's main chart, but not on Overview) */}
      <div
        className={`no-scrollbar flex gap-2 overflow-x-auto snap-x snap-mandatory pb-2 sm:grid ${includeTomorrow ? "sm:grid-cols-7" : "sm:grid-cols-6"} sm:gap-1.5 sm:overflow-visible sm:pb-0`}
      >
        {data.days
          .filter((day) => {
            if (includeTomorrow) return true;
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            return day.date !== tomorrow.toISOString().split("T")[0];
          })
          .map((day) => {
            const cfg = CLASS_CONFIG[day.classification] || CLASS_CONFIG.normal;
            const pctDiff = refAvg
              ? Math.round(((day.daily_avg - refAvg) / refAvg) * 100)
              : null;
            const d = new Date(day.date + "T12:00:00");
            const shortDate = d.toLocaleDateString("en-GB", {
              day: "numeric",
              month: "short",
            });
            // Qualitative confidence in the cheap/normal/expensive *call* — not
            // a probability the price lands on daily_avg. The underlying score
            // is distance-from-classification-boundary (0.5 at the edge → 1.0
            // deep in a bucket), so we show tiers, not a spurious percentage
            // that saturates to "100% likely" on extreme days. A calibrated
            // probability from forecast history is the planned replacement.
            const confTier =
              day.confidence === null
                ? null
                : day.confidence >= 0.8
                  ? "High"
                  : day.confidence >= 0.65
                    ? "Med"
                    : "Low";

            return (
              <div
                key={day.date}
                onClick={() => onDateSelect?.(day.date)}
                className={`min-w-[5.5rem] snap-center sm:min-w-0 rounded-xl border px-1.5 py-3 text-center ${cfg.bg} ${onDateSelect ? "cursor-pointer hover:brightness-110 transition-all" : ""}`}
              >
                <p className="text-xs text-content-muted truncate">
                  {SHORT_WEEKDAYS[day.weekday] || day.weekday} {shortDate}
                </p>
                <p
                  className={`text-xl sm:text-2xl font-bold ${cfg.color} mt-1`}
                >
                  {formatPrice(day.daily_avg)}
                </p>
                {pctDiff !== null && (
                  <p
                    className={`text-xs mt-1 font-medium ${pctDiff < 0 ? "text-cyan-600 dark:text-cyan-400" : pctDiff > 0 ? "text-orange-600 dark:text-orange-400" : "text-content-secondary"}`}
                  >
                    {pctDiff < 0 ? "\u2193" : pctDiff > 0 ? "\u2191" : ""}
                    {Math.abs(pctDiff)}%
                  </p>
                )}
                {day.is_actual ? (
                  <p className="mt-1">
                    <span className="inline-block rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide border border-current/30 text-content-secondary">
                      Actual
                    </span>
                  </p>
                ) : (
                  confTier !== null && (
                    <p
                      className="text-xs text-content-faint mt-1"
                      title="Confidence in the cheap / normal / expensive call — not the probability the price hits this figure."
                    >
                      {confTier} conf.
                    </p>
                  )
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
}
