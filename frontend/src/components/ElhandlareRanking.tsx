"use client";

import { useMemo } from "react";
import { useElhandlare } from "../hooks/useElhandlare";
import { useMonthlyAverages } from "../hooks/useMonthlyAverages";
import type { Area, ElhandlareEntry } from "../types/index";

const MOMS_RATE = 0.25;

type DwellingType = "lagenhet" | "villa_utan" | "villa_med";

interface Props {
  area: Area;
  dwelling: DwellingType;
  kwhYear: number;
}

const DWELLING_MESSAGE: Record<DwellingType, string> = {
  lagenhet:
    "With 2,000 kWh/year the monthly fee dominates. A 1 öre markup difference = 20 kr/year; a 24 kr/mån fee difference = 288 kr/year.",
  villa_utan:
    "At 5,000 kWh/year both the monthly fee and markup matter. Time-shifting with a 15-minute spot plan helps only if you have EV/heat-pump loads.",
  villa_med:
    "At 20,000 kWh/year markup dominates: 1 öre = 200 kr/year. Pair a 15-minute spot plan with smart heating control for further savings.",
};

const CONTRACT_TYPE_LABEL: Record<string, string> = {
  rorligt: "variable",
  kvartspris: "spot",
  fast: "fixed",
};

interface RankedRetailer extends ElhandlareEntry {
  spotCostSek: number;
  paslagCostSek: number;
  momsSek: number;
  monthlyFeeAnnualSek: number;
  totalAnnualSek: number;
}

function formatSek(n: number): string {
  return Math.round(n).toLocaleString("sv-SE");
}

export function ElhandlareRanking({ area, dwelling, kwhYear }: Props) {
  const { data: retailerData, loading: retailerLoading } = useElhandlare(area);
  const { data: spotData, loading: spotLoading } = useMonthlyAverages(12, area);

  // 12-month average spot price in öre/kWh (exkl moms)
  const spotAvgOreExkl = useMemo<number | null>(() => {
    if (!spotData?.months?.length) return null;
    const sum = spotData.months.reduce((s, m) => s + m.avg_sek_kwh, 0);
    return (sum / spotData.months.length) * 100;
  }, [spotData]);

  const ranked = useMemo<RankedRetailer[]>(() => {
    if (!retailerData?.retailers || spotAvgOreExkl == null) return [];
    return retailerData.retailers
      .map((r) => {
        const spotCostSek = (spotAvgOreExkl * kwhYear) / 100;
        const paslagCostSek = (r.paslag_ore_kwh * kwhYear) / 100;
        const momsSek = (spotCostSek + paslagCostSek) * MOMS_RATE;
        const monthlyFeeAnnualSek = r.monthly_fee_sek * 12;
        const totalAnnualSek =
          spotCostSek + paslagCostSek + momsSek + monthlyFeeAnnualSek;
        return {
          ...r,
          spotCostSek,
          paslagCostSek,
          momsSek,
          monthlyFeeAnnualSek,
          totalAnnualSek,
        };
      })
      .sort((a, b) => a.totalAnnualSek - b.totalAnnualSek);
  }, [retailerData, spotAvgOreExkl, kwhYear]);

  const loading = retailerLoading || spotLoading;

  return (
    <div className="space-y-4">
      {/* Ranking card */}
      <div className="bg-surface-primary rounded-2xl p-4 space-y-3">
        <div>
          <h2 className="text-base font-medium text-content-primary">
            Retailer comparison
          </h2>
          <p className="text-xs text-content-muted mt-0.5">
            {DWELLING_MESSAGE[dwelling]}
          </p>
          {spotAvgOreExkl != null && (
            <p className="text-[10px] text-content-muted mt-1">
              Based on {area} 12-month avg spot price{" "}
              {spotAvgOreExkl.toFixed(1)} öre/kWh (exkl moms), {kwhYear}{" "}
              kWh/year consumption
            </p>
          )}
        </div>

        {loading && (
          <div className="animate-pulse space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-14 bg-surface-secondary rounded-xl" />
            ))}
          </div>
        )}

        {!loading && ranked.length > 0 && (
          <div className="space-y-2">
            {ranked.map((r, idx) => (
              <div
                key={r.slug}
                className="flex items-center gap-3 px-3 py-3 rounded-xl bg-surface-secondary"
              >
                <div className="w-6 text-center text-sm font-semibold text-content-muted tabular-nums">
                  {idx + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-base font-medium text-content-primary">
                      {r.name}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-content-muted bg-surface-tertiary rounded px-1.5 py-0.5">
                      {CONTRACT_TYPE_LABEL[r.contract_type] ?? r.contract_type}
                    </span>
                    {r.is_estimate && (
                      <span
                        className="text-[10px] uppercase tracking-wide text-amber-600 dark:text-amber-400 bg-amber-500/10 rounded px-1.5 py-0.5"
                        title="Påslag figure is an estimate; company does not disclose"
                      >
                        estimated
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-content-muted mt-0.5 tabular-nums">
                    {r.paslag_ore_kwh.toFixed(1)} öre markup ·{" "}
                    {formatSek(r.monthly_fee_sek)} kr/mån
                  </div>
                </div>
                <div className="text-right whitespace-nowrap">
                  <div className="text-sm font-semibold text-content-primary tabular-nums">
                    {formatSek(r.totalAnnualSek)} kr
                  </div>
                  <div className="text-[10px] text-content-muted">per year</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Transparency section */}
      <div className="bg-surface-primary rounded-2xl p-4 space-y-3">
        <div>
          <h2 className="text-base font-medium text-content-primary">
            Why these numbers don&apos;t tell the whole story
          </h2>
          <p className="text-xs text-content-muted mt-0.5">
            Each company defines &quot;markup&quot; differently. The same 0 öre
            can hide 8 öre in purchase costs.
          </p>
        </div>

        {!loading && ranked.length > 0 && (
          <div className="space-y-2">
            {ranked.map((r) => (
              <div
                key={`def-${r.slug}`}
                className="px-3 py-2 rounded-lg bg-surface-secondary"
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="text-base font-medium text-content-primary">
                    {r.name}
                  </span>
                  <span className="text-[11px] text-content-muted tabular-nums">
                    markup {r.paslag_ore_kwh.toFixed(1)} öre
                    {r.elcert_included && " (incl. green cert)"}
                  </span>
                </div>
                {r.notes && (
                  <p className="text-[11px] text-content-muted mt-1 leading-relaxed">
                    {r.notes}
                  </p>
                )}
                {r.source_url && (
                  <a
                    href={r.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] text-sky-600 dark:text-sky-400 hover:underline mt-1 inline-block"
                  >
                    source →
                  </a>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="pt-2 border-t border-surface-tertiary/40">
          <p className="text-[11px] text-content-muted leading-relaxed">
            <span className="font-medium text-content-secondary">
              Not shown above:
            </span>{" "}
            Cheap Energy, Bixia and Mölndals Energi don&apos;t publish their
            markup in a comparable form — so they can&apos;t be ranked against
            these 5 companies. That opacity is itself informative when choosing
            a retailer.
          </p>
          <p className="text-[11px] text-content-muted mt-2 leading-relaxed">
            Figures are annual estimates based on publicly disclosed markup,
            monthly fees, and {area} spot price averages. Verify with each
            retailer before signing.
          </p>
        </div>
      </div>
    </div>
  );
}
