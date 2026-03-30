/**
 * Format a UTC ISO timestamp to CET/CEST local hour label, e.g. "14:00"
 * Sweden is UTC+1 (winter) / UTC+2 (summer).
 * Using 'Europe/Stockholm' locale for correct DST handling.
 */
export function toLocalHour(isoString: string): string {
  return new Date(isoString).toLocaleTimeString("sv-SE", {
    timeZone: "Europe/Stockholm",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Current hour in CET, 0–23, for highlighting the active slot.
 */
export function currentCETHour(): number {
  const now = new Date();
  return parseInt(
    now.toLocaleString("sv-SE", {
      timeZone: "Europe/Stockholm",
      hour: "2-digit",
      hour12: false,
    }),
    10,
  );
}

/**
 * Append short weekday to an ISO date string, e.g. "2024-03-16" → "2024-03-16 (Sat)"
 */
export function dateWithWeekday(isoDate: string): string {
  const d = new Date(isoDate + "T12:00:00Z");
  const wd = d.toLocaleDateString("en-SE", { weekday: "short" });
  return `${isoDate} (${wd})`;
}

/**
 * Current CET time floored to 15-minute intervals, e.g. "16:15"
 */
export function currentCETTime15(): string {
  const now = new Date();
  const parts = now.toLocaleTimeString("sv-SE", {
    timeZone: "Europe/Stockholm",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const [h, m] = parts.split(":");
  const floored = Math.floor(parseInt(m, 10) / 15) * 15;
  return `${h}:${String(floored).padStart(2, "0")}`;
}
