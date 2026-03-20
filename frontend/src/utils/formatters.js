/**
 * Format a UTC ISO timestamp to CET/CEST local hour label, e.g. "14:00"
 * Sweden is UTC+1 (winter) / UTC+2 (summer).
 * Using 'Europe/Stockholm' locale for correct DST handling.
 */
export function toLocalHour(isoString) {
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
export function currentCETHour() {
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
 * Current CET time floored to 15-minute intervals, e.g. "16:15"
 */
export function currentCETTime15() {
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
