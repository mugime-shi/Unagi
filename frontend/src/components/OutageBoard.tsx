"use client";

import { useOutages } from "../hooks/useOutages";
import type { NuclearUnit } from "../types/index";

const STATUS_STYLE: Record<
  NuclearUnit["status"],
  { label: string; pill: string; bar: string }
> = {
  running: {
    label: "Running",
    pill: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
    bar: "bg-emerald-500",
  },
  reduced: {
    label: "Reduced",
    pill: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
    bar: "bg-amber-500",
  },
  offline: {
    label: "Offline",
    pill: "bg-rose-500/15 text-rose-700 dark:text-rose-400",
    bar: "bg-rose-500",
  },
};

const REASON_MAX = 60;

function gw(mw: number): string {
  return (mw / 1000).toFixed(1);
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

/** "12 Dec" in Stockholm time (display only). */
function backDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    timeZone: "Europe/Stockholm",
    day: "numeric",
    month: "short",
  });
}

function ReactorTile({ unit }: { unit: NuclearUnit }) {
  const style = STATUS_STYLE[unit.status];
  const pct = Math.max(
    0,
    Math.min(100, (unit.available_mw / unit.nominal_mw) * 100),
  );
  const reason = unit.outage?.reason ?? "";
  return (
    <div className="bg-surface-secondary rounded-xl p-3 min-w-0">
      {/* Wraps the pill under the name on narrow tiles instead of truncating "Forsmark 1" */}
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <p className="text-sm font-medium text-content-primary whitespace-nowrap">
          {unit.name}
        </p>
        <span
          className={`shrink-0 text-[10px] font-medium rounded-full px-2 py-0.5 ${style.pill}`}
        >
          {style.label}
        </span>
      </div>
      <p className="text-xs text-content-muted tabular-nums mt-1.5">
        {Math.round(unit.available_mw)} / {unit.nominal_mw} MW
      </p>
      <div className="h-1 rounded-full bg-surface-tertiary mt-1 overflow-hidden">
        <div
          className={`h-full rounded-full ${style.bar}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {unit.outage && (
        <div className="mt-2 space-y-0.5">
          {reason && (
            <p
              className="text-[11px] text-content-secondary break-words"
              title={reason}
            >
              {truncate(reason, REASON_MAX)}
            </p>
          )}
          <p className="text-[11px] text-content-muted">
            {unit.outage.type === "forced" ? "Forced · " : ""}
            Back {backDate(unit.outage.end)}
          </p>
        </div>
      )}
    </div>
  );
}

export function OutageBoard({ date }: { date?: string | null }) {
  const { data, loading, error } = useOutages(date);

  if (!data) {
    if (loading) {
      return (
        <div className="bg-surface-primary rounded-2xl p-4 animate-pulse space-y-3">
          <div className="h-5 w-1/3 bg-surface-secondary rounded" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-24 bg-surface-secondary rounded-xl" />
            ))}
          </div>
        </div>
      );
    }
    if (error) {
      return (
        <div className="bg-surface-primary rounded-2xl p-4">
          <h2 className="text-base font-medium text-content-primary">
            Nuclear power
          </h2>
          <p className="text-sm text-content-muted mt-1">
            Outage data is unavailable right now.
          </p>
        </div>
      );
    }
    return null;
  }

  const total = data.nuclear.reduce((sum, u) => sum + u.nominal_mw, 0);
  const offlineMw = data.nuclear_offline_mw;
  const summary =
    offlineMw > 0
      ? `${gw(offlineMw)} GW of ${gw(total)} GW offline`
      : `All ${data.nuclear.length} reactors running`;

  return (
    <div className="bg-surface-primary rounded-2xl p-4 space-y-3">
      <div>
        <h2 className="text-base font-medium text-content-primary">
          Nuclear power
          <span className="text-content-muted ml-1.5 font-normal">
            {summary}
          </span>
        </h2>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {data.nuclear.map((u) => (
          <ReactorTile key={u.name} unit={u} />
        ))}
      </div>

      {data.other.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-content-secondary mb-1.5">
            Other large outages
          </h3>
          <ul className="space-y-1">
            {data.other.map((o) => (
              <li
                key={`${o.area}-${o.name}`}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <span className="min-w-0 truncate text-content-primary">
                  {o.name}
                  <span className="text-content-muted"> · {o.area}</span>
                </span>
                <span className="shrink-0 tabular-nums text-content-secondary">
                  −{Math.round(o.nominal_mw - o.available_mw)} MW
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-[10px] text-content-faint">
        Source: ENTSO-E Transparency Platform
      </p>
    </div>
  );
}
