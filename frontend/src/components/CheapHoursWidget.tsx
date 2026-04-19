import { useCheapHours } from "../hooks/useCheapHours";
import { formatPrice, PRICE_UNIT, toLocalHour } from "../utils/formatters";
import type { Area } from "../types/index";

interface Appliance {
  name: string;
  duration: number;
  emoji: string;
}

const APPLIANCES: Appliance[] = [
  { name: "Washing machine", duration: 2, emoji: "\u{1FAE7}" },
  { name: "Dishwasher", duration: 2, emoji: "\u{1F37D}\uFE0F" },
  { name: "EV charging", duration: 4, emoji: "\u26A1" },
];

interface ApplianceRowProps {
  name: string;
  emoji: string;
  duration: number;
  date: string;
  area: Area;
}

function ApplianceRow({
  name,
  emoji,
  duration,
  date,
  area,
}: ApplianceRowProps) {
  const { data, loading } = useCheapHours(date, duration, area);

  const skeletonRow = (
    <div className="flex items-center justify-between py-2.5 border-b border-surface-tertiary last:border-0">
      <div className="flex items-center gap-2">
        <span className="text-base">{emoji}</span>
        <span className="text-sm text-content-secondary">{name}</span>
        <span className="text-xs text-content-faint">({duration}h)</span>
      </div>
      <span className="text-xs text-content-faint">&mdash;</span>
    </div>
  );

  if (loading || !data?.cheapest_window) return skeletonRow;

  const w = data.cheapest_window;
  const start = toLocalHour(w.start_utc);
  const end = toLocalHour(w.end_utc);

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-surface-tertiary last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-base shrink-0">{emoji}</span>
        <span className="text-sm truncate text-content-primary">{name}</span>
        <span className="text-xs text-content-faint shrink-0">
          ({duration}h)
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-2">
        <span className="text-sm font-medium text-cyan-600 dark:text-cyan-400">
          {start}–{end}
        </span>
        <span className="text-xs text-content-muted">
          {formatPrice(w.avg_sek_kwh)}
        </span>
      </div>
    </div>
  );
}

interface CheapHoursWidgetProps {
  date: string;
  area?: Area;
}

export function CheapHoursWidget({
  date,
  area = "SE3",
}: CheapHoursWidgetProps) {
  return (
    <div className="bg-surface-primary rounded-2xl p-4">
      <h2 className="text-base font-medium text-content-primary mb-1">
        Best time to run today
      </h2>
      <p className="text-xs text-content-faint mb-3">
        Cheapest consecutive window per appliance
      </p>
      <div className="flex justify-end mb-1">
        <span className="text-xs text-content-faint">{PRICE_UNIT}</span>
      </div>
      {APPLIANCES.map((a) => (
        <ApplianceRow key={a.name} {...a} date={date} area={area} />
      ))}
    </div>
  );
}
