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
    <div className="flex items-center justify-between py-2.5 border-b border-sea-800 last:border-0">
      <div className="flex items-center gap-2">
        <span className="text-base">{emoji}</span>
        <span className="text-sm text-gray-400">{name}</span>
        <span className="text-xs text-gray-600">({duration}h)</span>
      </div>
      <span className="text-xs text-gray-600">&mdash;</span>
    </div>
  );

  if (loading || !data?.cheapest_window) return skeletonRow;

  const w = data.cheapest_window;
  const start = toLocalHour(w.start_utc);
  const end = toLocalHour(w.end_utc);

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-sea-800 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-base shrink-0">{emoji}</span>
        <span className="text-sm truncate">{name}</span>
        <span className="text-xs text-gray-600 shrink-0">({duration}h)</span>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-2">
        <span className="text-sm font-medium text-cyan-400">
          {start}–{end}
        </span>
        <span className="text-xs text-gray-500">
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
    <div className="bg-sea-900 rounded-2xl p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-1">
        Best time to run today
      </h2>
      <p className="text-xs text-gray-600 mb-3">
        Cheapest consecutive window per appliance
      </p>
      <div className="flex justify-end mb-1">
        <span className="text-xs text-gray-600">{PRICE_UNIT}</span>
      </div>
      {APPLIANCES.map((a) => (
        <ApplianceRow key={a.name} {...a} date={date} area={area} />
      ))}
    </div>
  );
}
