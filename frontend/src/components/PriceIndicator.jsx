import {
  currentCETHour,
  currentCETTime15,
  toLocalHour,
} from "../utils/formatters";

const NOW_HOUR = currentCETHour();

export function PriceIndicator({ prices }) {
  if (!prices?.length) return null;

  // Find the slot matching the current CET hour
  const current =
    prices.find((p) => {
      const h = parseInt(toLocalHour(p.timestamp_utc).split(":")[0], 10);
      return h === NOW_HOUR;
    }) ?? prices[0];

  const sek = parseFloat(current.price_sek_kwh);
  const avg =
    prices.reduce((s, p) => s + parseFloat(p.price_sek_kwh), 0) / prices.length;

  let level, color, bg;
  if (sek <= avg * 0.8) {
    level = "Cheap";
    color = "text-green-300";
    bg = "bg-green-950/40 border-green-800/40";
  } else if (sek >= avg * 1.2) {
    level = "Expensive";
    color = "text-red-300";
    bg = "bg-red-950/40 border-red-800/40";
  } else {
    level = "Normal";
    color = "text-gray-200";
    bg = "bg-sea-800/50 border-sea-700/40";
  }

  return (
    <div className={`rounded-xl border px-5 py-4 ${bg}`}>
      <p className="text-xs text-gray-400 mb-1">
        Right now ({currentCETTime15()} CET)
      </p>
      <div className="flex items-baseline gap-3">
        <span className={`text-3xl font-bold ${color}`}>{sek.toFixed(2)}</span>
        <span className="text-gray-400 text-sm">SEK/kWh</span>
        <span className={`text-sm font-medium ${color}`}>{level}</span>
      </div>
      <p className="text-xs text-gray-500 mt-1">
        Daily avg: {avg.toFixed(2)} SEK/kWh
      </p>
    </div>
  );
}
