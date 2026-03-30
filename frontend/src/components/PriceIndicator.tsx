import {
  currentCETHour,
  currentCETTime15,
  toLocalHour,
} from "../utils/formatters";
import type { PricePoint } from "../types/index";

const NOW_HOUR = currentCETHour();

interface PriceIndicatorProps {
  prices: PricePoint[];
}

export function PriceIndicator({ prices }: PriceIndicatorProps) {
  if (!prices?.length) return null;

  // Find the slot matching the current CET hour
  const current =
    prices.find((p) => {
      const h = parseInt(toLocalHour(p.timestamp_utc).split(":")[0], 10);
      return h === NOW_HOUR;
    }) ?? prices[0];

  const sek = Number(current.price_sek_kwh);
  const avg =
    prices.reduce((s, p) => s + Number(p.price_sek_kwh), 0) / prices.length;

  let level: string, color: string, bg: string;
  if (sek <= avg * 0.82) {
    level = "Cheap";
    color = "text-cyan-300";
    bg = "bg-cyan-950/40 border-cyan-800/40";
  } else if (sek >= avg * 1.18) {
    level = "Expensive";
    color = "text-orange-300";
    bg = "bg-orange-950/40 border-orange-800/40";
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
      <div className="flex items-baseline gap-2">
        <span className={`text-3xl font-bold ${color}`}>{sek.toFixed(2)}</span>
        <span className="text-gray-400 text-sm">SEK/kWh</span>
      </div>
      <p className="text-xs text-gray-500 mt-1">
        <span className={`font-medium ${color}`}>{level}</span>
        {" · "}avg {avg.toFixed(2)} SEK/kWh vs today
      </p>
    </div>
  );
}
