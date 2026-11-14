import { useMounted } from "../hooks/useMounted";
import { useRefresh } from "../hooks/useRefresh";

// Fixed zone (Swedish market time) so the label is stable regardless of the
// viewer's locale — and identical between renders.
const STOCKHOLM = { timeZone: "Europe/Stockholm" } as const;
const dayKey = (d: Date) =>
  new Intl.DateTimeFormat("sv-SE", { ...STOCKHOLM, dateStyle: "short" }).format(
    d,
  );

function formatUpdated(d: Date, timeOnly: boolean): string {
  // Time alone only while it is still that day — a tab left open overnight must not show a bare, stale time.
  const showDate = !timeOnly || dayKey(d) !== dayKey(new Date());
  return new Intl.DateTimeFormat("sv-SE", {
    ...STOCKHOLM,
    ...(showDate && { year: "numeric", month: "2-digit", day: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

/** `timeOnly`: the page already shows today's date nearby, so repeat only the time. */
export function UpdateBadge({ timeOnly = false }: { timeOnly?: boolean }) {
  const { lastUpdatedAt, bump } = useRefresh();
  // `lastUpdatedAt` is a client-side "now" — its instant (and the runtime
  // timezone) differ between SSR and hydration, which would trip a hydration
  // mismatch. Render the timestamp only after mount so both passes agree.
  const mounted = useMounted();

  return (
    <div className="flex items-center gap-1.5 text-xs text-content-muted">
      <span className="tabular-nums">
        Updated {mounted ? formatUpdated(lastUpdatedAt, timeOnly) : "—"}
      </span>
      <button
        onClick={bump}
        className="p-1 rounded hover:text-content-primary hover:bg-surface-secondary transition-colors"
        aria-label="Refresh data"
        title="Refresh data"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
      </button>
    </div>
  );
}
