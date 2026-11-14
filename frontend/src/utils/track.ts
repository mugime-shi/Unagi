import { apiFetch } from "./api";

/**
 * First-party, ID-less usage events (backend: POST /api/v1/events).
 *
 * Vercel Analytics resets its visitor hash daily, so it cannot tell a
 * returning visitor from a new one. We keep the first/last visit dates in
 * localStorage and send only the day offsets — never an identifier.
 */

const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const VISIT_KEY = "unagi.visit";

// Preview deployments proxy /api to the production API too; only count the
// real site (and localhost, which talks to the local API).
const TRACKED_HOSTS = new Set(["unagieel.net", "localhost", "127.0.0.1"]);

type UsageEvent =
  | "visit"
  | "layer_view"
  | "tab_view"
  | "area_select"
  | "engagement"
  | "action";

interface VisitState {
  first: string; // YYYY-MM-DD, Europe/Stockholm
  last: string;
}

function trackingAllowed(): boolean {
  if (typeof window === "undefined") return false;
  if (!TRACKED_HOSTS.has(window.location.hostname)) return false;
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean };
  return !(nav.globalPrivacyControl || nav.doNotTrack === "1");
}

function send(body: Record<string, unknown>): void {
  apiFetch(`${API_BASE}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => {
    // Analytics must never surface errors to the user.
  });
}

/** Local calendar day in Sweden — matches how the backend buckets visits. */
function stockholmDay(d: Date = new Date()): string {
  return d.toLocaleDateString("sv-SE", { timeZone: "Europe/Stockholm" });
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

function externalReferrer(): string | undefined {
  try {
    const host = new URL(document.referrer).hostname.replace(/^www\./, "");
    return host && host !== window.location.hostname ? host : undefined;
  } catch {
    return undefined;
  }
}

export function trackEvent(
  event: Exclude<UsageEvent, "visit">,
  label: string,
): void {
  if (!trackingAllowed()) return;
  send({ event, label });
}

/** At most one `visit` per browser per Stockholm day. */
export function trackVisit(): void {
  if (!trackingAllowed()) return;

  const today = stockholmDay();
  let prev: VisitState | null = null;
  try {
    const raw = localStorage.getItem(VISIT_KEY);
    prev = raw ? (JSON.parse(raw) as VisitState) : null;
    if (prev?.last === today) return;
    localStorage.setItem(
      VISIT_KEY,
      JSON.stringify({
        first: prev?.first ?? today,
        last: today,
      } satisfies VisitState),
    );
  } catch {
    // Without storage every load would look like a new visitor — skip.
    return;
  }

  const sinceFirst = prev ? daysBetween(prev.first, today) : 0;
  const sinceLast = prev ? daysBetween(prev.last, today) : null;
  // A corrupted or clock-skewed entry would be rejected by the API anyway.
  if (
    !(sinceFirst >= 0) ||
    (sinceLast !== null && !(sinceLast >= 0 && sinceLast <= sinceFirst))
  )
    return;

  send({
    event: "visit",
    label: externalReferrer(),
    days_since_first: sinceFirst,
    days_since_last: sinceLast,
  });
}

// Visible-time milestones. Sent while the page is still open because leave
// events are not delivered reliably on mobile.
const MILESTONES: { label: string; at: number }[] = [
  { label: "10s", at: 10_000 },
  { label: "1m", at: 60_000 },
  { label: "5m", at: 300_000 },
];

// Module-level so React StrictMode's mount/unmount/mount cannot send `start`
// twice or reset the clock; each page load counts each label at most once.
let engagementStarted = false;
let visibleElapsed = 0;
const milestonesSent = new Set<string>();

/**
 * Sends `start`, then `10s` / `1m` / `5m` once the page has been visible for
 * that long in total. The clock pauses while the tab is hidden.
 */
export function trackEngagement(): () => void {
  if (!trackingAllowed()) return () => {};
  if (!engagementStarted) {
    engagementStarted = true;
    trackEvent("engagement", "start");
  }

  let visibleSince: number | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const bank = (): void => {
    if (visibleSince === null) return;
    const now = performance.now();
    visibleElapsed += now - visibleSince;
    visibleSince = now;
  };

  const schedule = (): void => {
    clearTimeout(timer);
    if (visibleSince === null) return;
    const next = MILESTONES.find((m) => !milestonesSent.has(m.label));
    if (!next) return;
    const waited = performance.now() - visibleSince;
    timer = setTimeout(
      () => {
        bank();
        for (const m of MILESTONES) {
          if (visibleElapsed >= m.at && !milestonesSent.has(m.label)) {
            milestonesSent.add(m.label);
            trackEvent("engagement", m.label);
          }
        }
        schedule();
      },
      Math.max(0, next.at - visibleElapsed - waited),
    );
  };

  const onVisibility = (): void => {
    if (document.visibilityState === "visible") {
      visibleSince = performance.now();
    } else {
      bank();
      visibleSince = null;
    }
    schedule();
  };

  onVisibility();
  document.addEventListener("visibilitychange", onVisibility);
  return () => {
    bank();
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
