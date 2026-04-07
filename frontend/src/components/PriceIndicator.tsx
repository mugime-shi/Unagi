import {
  currentCETHour,
  currentCETTime15,
  formatPrice,
  PRICE_UNIT,
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
    color = "text-cyan-500 dark:text-cyan-300";
    bg =
      "bg-[var(--indicator-cheap-bg)] border-[var(--indicator-cheap-border)]";
  } else if (sek >= avg * 1.18) {
    level = "Expensive";
    color = "text-orange-600 dark:text-orange-300";
    bg =
      "bg-[var(--indicator-expensive-bg)] border-[var(--indicator-expensive-border)]";
  } else {
    level = "Normal";
    color = "text-content-primary";
    bg =
      "bg-[var(--indicator-normal-bg)] border-[var(--indicator-normal-border)]";
  }

  return (
    <div className={`rounded-xl border px-5 py-4 ${bg}`}>
      <p className="text-xs text-content-secondary mb-1">
        Right now ({currentCETTime15()} CET)
      </p>
      <div className="flex items-baseline gap-2">
        <span className={`text-3xl font-bold ${color}`}>
          {formatPrice(sek)}
        </span>
        <span className="text-content-secondary text-sm">{PRICE_UNIT}</span>
      </div>
      <p className="text-xs text-content-muted mt-1">
        <span className={`font-medium ${color}`}>{level}</span>
        {" · "}avg {formatPrice(avg)} {PRICE_UNIT} vs today
      </p>
    </div>
  );
}
