// The API treats dates as Stockholm calendar days. `toISOString()` is UTC, which
// is a day behind between 00:00 and 01:00/02:00 Stockholm time.
const STOCKHOLM_DATE = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Europe/Stockholm",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** Stockholm calendar date (YYYY-MM-DD) of the given instant, default now. */
export function stockholmDateISO(d: Date = new Date()): string {
  return STOCKHOLM_DATE.format(d);
}

/** Pure calendar arithmetic on a YYYY-MM-DD string, independent of the local timezone. */
export function addDaysISO(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().split("T")[0];
}
