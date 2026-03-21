import { useCheapHours } from "../hooks/useCheapHours";
import { toLocalHour } from "../utils/formatters";

const APPLIANCES = [
  { name: "Washing machine", duration: 2, emoji: "🫧" },
  { name: "Dishwasher", duration: 2, emoji: "🍽️" },
  { name: "EV charging", duration: 4, emoji: "⚡" },
];

function ApplianceRow({ name, emoji, duration, date, area }) {
  const { data, loading } = useCheapHours(date, duration, area);

  const skeletonRow = (
    <div className="flex items-center justify-between py-2.5 border-b border-gray-800 last:border-0">
      <div className="flex items-center gap-2">
        <span className="text-base">{emoji}</span>
        <span className="text-sm text-gray-400">{name}</span>
        <span className="text-xs text-gray-600">({duration}h)</span>
      </div>
      <span className="text-xs text-gray-600">—</span>
    </div>
  );

  if (loading || !data?.cheapest_window) return skeletonRow;

  const w = data.cheapest_window;
  const start = toLocalHour(w.start_utc);
  const end = toLocalHour(w.end_utc);

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-gray-800 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-base shrink-0">{emoji}</span>
        <span className="text-sm truncate">{name}</span>
        <span className="text-xs text-gray-600 shrink-0">({duration}h)</span>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-2">
        <span className="text-sm font-medium text-green-400">
          {start}–{end}
        </span>
        <span className="text-xs text-gray-500">
          {w.avg_sek_kwh.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

export function CheapHoursWidget({ date, area = "SE3" }) {
  return (
    <div className="bg-gray-900 rounded-2xl p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-1">
        Best time to run today
      </h2>
      <p className="text-xs text-gray-600 mb-3">
        Cheapest consecutive window per appliance
      </p>
      <div className="flex justify-end mb-1">
        <span className="text-xs text-gray-600">SEK/kWh</span>
      </div>
      {APPLIANCES.map((a) => (
        <ApplianceRow key={a.name} {...a} date={date} area={area} />
      ))}
    </div>
  );
}
