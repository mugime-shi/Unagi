import { FormEvent, ReactElement, useState } from "react";
import { useSolar } from "../hooks/useSolar";

// Extended solar result from the API (richer than SolarResult in types/index.ts)
interface SolarApiResult {
  data_source: string;
  month: string;
  panel_kwp: number;
  battery_kwh: number;
  avg_spot_sek_kwh: number;
  solar_generation_kwh: number;
  self_consumed_kwh: number;
  sold_to_grid_kwh: number;
  bought_from_grid_kwh: number;
  revenue_sek: number;
  savings_from_self_consumption_sek: number;
  battery_effect_sek: number;
  total_benefit_with_tax_credit_sek: number;
  total_benefit_without_tax_credit_sek: number;
  tax_credit: {
    applies: boolean;
    rate_sek_kwh: number;
    eligible_kwh: number;
    annual_cap_sek: number;
    monthly_credit_sek: number;
  };
  baseline: {
    total_benefit_sek: number;
    sold_to_grid_kwh: number;
    bought_from_grid_kwh: number;
  };
}

interface ChipProps {
  label: string;
  value: string;
  unit: string;
}

interface FieldInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min: string;
  max: string;
  step: string;
  unit: string;
  width?: string;
  pr?: string;
}

function currentMonthISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function Chip({ label, value, unit }: ChipProps): ReactElement {
  return (
    <div className="bg-sea-800 rounded-xl p-3 text-center">
      <p className="text-xs text-gray-400 mb-0.5 leading-tight">{label}</p>
      <p className="text-base font-semibold">{value}</p>
      <p className="text-xs text-gray-500">{unit}</p>
    </div>
  );
}

function FieldInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  unit,
  width = "w-32",
  pr = "pr-12",
}: FieldInputProps): ReactElement {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-gray-400">{label}</label>
      <div className="relative">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`bg-sea-800 border border-sea-700 rounded-lg px-3 py-1.5 text-sm ${width} ${pr}`}
          min={min}
          max={max}
          step={step}
        />
        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500">
          {unit}
        </span>
      </div>
    </div>
  );
}

export function SolarSimulator(): ReactElement {
  const [panelKwp, setPanelKwp] = useState<string>("6.0");
  const [batteryKwh, setBatteryKwh] = useState<string>("0");
  const [annualKwh, setAnnualKwh] = useState<string>("15000");
  const [month, setMonth] = useState<string>(currentMonthISO);
  const { result: rawResult, loading, error, run } = useSolar();

  // Cast to the extended API shape
  const result = rawResult as unknown as SolarApiResult | null;

  const handleSubmit = (e: FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    run({
      panel_kwp: parseFloat(panelKwp),
      battery_kwh: parseFloat(batteryKwh),
      annual_consumption_kwh: parseFloat(annualKwh),
      month,
    });
  };

  return (
    <div className="bg-sea-900 rounded-2xl p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-1">
        Solar PV simulator
      </h2>
      <p className="text-xs text-gray-600 mb-3">
        Estimate monthly generation, revenue &amp; self-consumption savings
        under current rules, and compare against the old 2025 tax credit.
      </p>

      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap gap-3 mb-4 items-end"
      >
        <FieldInput
          label="Panel capacity"
          value={panelKwp}
          onChange={setPanelKwp}
          min="1"
          max="100"
          step="0.5"
          unit="kWp"
        />
        <FieldInput
          label="Battery"
          value={batteryKwh}
          onChange={setBatteryKwh}
          min="0"
          max="200"
          step="1"
          unit="kWh"
        />
        <FieldInput
          label="Annual usage"
          value={annualKwh}
          onChange={setAnnualKwh}
          min="0"
          max="100000"
          step="1000"
          unit="kWh/y"
          width="w-36"
          pr="pr-14"
        />

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-400">Month</label>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-1.5 text-sm w-36 text-gray-100"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-sm transition-colors"
        >
          {loading ? "Simulating\u2026" : "Simulate"}
        </button>
      </form>

      {error && (
        <p className="text-red-400 text-xs mb-3">
          {error.message.includes("503") ||
          error.message.toLowerCase().includes("no spot price")
            ? `No spot price data for ${month}. Run backfill for that month first.`
            : error.message}
        </p>
      )}

      {result && (
        <div className="space-y-4">
          {/* Header: data source + month */}
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`text-xs px-2 py-0.5 rounded-full ${
                result.data_source === "smhi"
                  ? "bg-blue-500/20 text-blue-400"
                  : "bg-sea-700 text-gray-400"
              }`}
            >
              {result.data_source === "smhi"
                ? "SMHI real data"
                : "Reference table"}
            </span>
            <span className="text-xs text-gray-600">
              {result.month} &middot; {result.panel_kwp} kWp
              {result.battery_kwh > 0 &&
                ` \u00b7 ${result.battery_kwh} kWh battery`}
              {" \u00b7 "}avg spot {result.avg_spot_sek_kwh.toFixed(2)} SEK/kWh
            </span>
          </div>

          {/* Energy balance */}
          <div>
            <p className="text-xs text-gray-500 mb-2">Energy balance</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Chip
                label="Generated"
                value={result.solar_generation_kwh.toFixed(0)}
                unit="kWh"
              />
              <Chip
                label="Self-consumed"
                value={result.self_consumed_kwh.toFixed(0)}
                unit="kWh"
              />
              <Chip
                label="Sold to grid"
                value={result.sold_to_grid_kwh.toFixed(0)}
                unit="kWh"
              />
              <Chip
                label="Bought from grid"
                value={result.bought_from_grid_kwh.toFixed(0)}
                unit="kWh"
              />
            </div>
          </div>

          {/* Revenue & savings */}
          <div>
            <p className="text-xs text-gray-500 mb-2">Revenue &amp; savings</p>
            <div
              className={`grid gap-2 ${result.battery_kwh > 0 ? "grid-cols-3" : "grid-cols-2"}`}
            >
              <Chip
                label="Revenue (sold)"
                value={result.revenue_sek.toFixed(0)}
                unit="SEK/mo"
              />
              <Chip
                label="Savings (self-use)"
                value={result.savings_from_self_consumption_sek.toFixed(0)}
                unit="SEK/mo"
              />
              {result.battery_kwh > 0 && (
                <Chip
                  label="Battery effect"
                  value={
                    (result.battery_effect_sek >= 0 ? "+" : "") +
                    result.battery_effect_sek.toFixed(0)
                  }
                  unit="SEK/mo"
                />
              )}
            </div>
          </div>

          {/* Battery comparison — only when battery > 0 */}
          {result.battery_kwh > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">
                Battery impact — {result.battery_kwh} kWh battery vs no battery
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-blue-900/25 border border-blue-800/40 rounded-xl p-3 text-center">
                  <p className="text-xs text-blue-400/70 mb-1">with battery</p>
                  <p className="text-2xl font-bold text-blue-400">
                    {result.total_benefit_without_tax_credit_sek.toFixed(0)}
                  </p>
                  <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                  <p className="text-xs text-gray-600">
                    sold {result.sold_to_grid_kwh.toFixed(0)} kWh &middot;
                    bought {result.bought_from_grid_kwh.toFixed(0)} kWh
                  </p>
                </div>
                <div className="bg-sea-800/40 border border-sea-700/40 rounded-xl p-3 text-center">
                  <p className="text-xs text-gray-400/70 mb-1">
                    without battery
                  </p>
                  <p className="text-2xl font-bold text-gray-300">
                    {result.baseline.total_benefit_sek.toFixed(0)}
                  </p>
                  <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                  <p className="text-xs text-gray-600">
                    sold {result.baseline.sold_to_grid_kwh.toFixed(0)} kWh
                    &middot; bought{" "}
                    {result.baseline.bought_from_grid_kwh.toFixed(0)} kWh
                  </p>
                </div>
              </div>
              <p
                className="text-xs text-center mt-2 font-medium"
                style={{
                  color: result.battery_effect_sek >= 0 ? "#22d3ee" : "#fb923c",
                }}
              >
                Battery adds {result.battery_effect_sek >= 0 ? "+" : ""}
                {result.battery_effect_sek.toFixed(0)} SEK/month
              </p>
            </div>
          )}

          {/* Total benefit — context-aware display */}
          <div>
            {result.tax_credit.applies ? (
              /* -- 2025 and earlier: show with-credit vs without-credit comparison -- */
              <>
                <p className="text-xs text-gray-500 mb-2">
                  Total benefit — skattereduktion impact ({result.month})
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-cyan-900/25 border border-cyan-800/40 rounded-xl p-3 text-center">
                    <p className="text-xs text-cyan-400/70 mb-1">
                      with tax credit
                    </p>
                    <p className="text-2xl font-bold text-cyan-400">
                      {result.total_benefit_with_tax_credit_sek.toFixed(0)}
                    </p>
                    <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                    <p className="text-xs text-cyan-400/60">
                      ~
                      {(result.total_benefit_with_tax_credit_sek * 12).toFixed(
                        0,
                      )}{" "}
                      SEK / year
                    </p>
                    <p className="text-xs text-cyan-400/50 mt-1">
                      incl. {result.tax_credit.monthly_credit_sek.toFixed(0)}{" "}
                      SEK credit
                    </p>
                  </div>
                  <div className="bg-sea-800/40 border border-sea-700/40 rounded-xl p-3 text-center">
                    <p className="text-xs text-gray-400/70 mb-1">
                      without tax credit
                    </p>
                    <p className="text-2xl font-bold text-gray-300">
                      {result.total_benefit_without_tax_credit_sek.toFixed(0)}
                    </p>
                    <p className="text-xs text-gray-500 mb-1">SEK / month</p>
                    <p className="text-xs text-gray-500">
                      ~
                      {(
                        result.total_benefit_without_tax_credit_sek * 12
                      ).toFixed(0)}{" "}
                      SEK / year
                    </p>
                  </div>
                </div>
                <p className="text-xs text-gray-600 text-center mt-2">
                  Skattereduktion: {result.tax_credit.rate_sek_kwh} SEK/kWh
                  {" \u00b7 "}
                  {result.tax_credit.eligible_kwh.toFixed(0)} kWh eligible
                  {" \u00b7 "}annual cap{" "}
                  {result.tax_credit.annual_cap_sek.toLocaleString()} SEK
                </p>
              </>
            ) : (
              /* -- 2026 onwards: single benefit card, credit abolished -- */
              <>
                <p className="text-xs text-gray-500 mb-2">
                  Total benefit ({result.month})
                </p>
                <div className="bg-sea-800/40 border border-sea-700/40 rounded-xl p-4 text-center">
                  <p className="text-3xl font-bold text-gray-100">
                    {result.total_benefit_without_tax_credit_sek.toFixed(0)}
                  </p>
                  <p className="text-sm text-gray-500 mb-2">SEK / month</p>
                  <p className="text-base text-gray-400">
                    ~
                    {(result.total_benefit_without_tax_credit_sek * 12).toFixed(
                      0,
                    )}{" "}
                    SEK / year
                  </p>
                </div>
                <p className="text-xs text-gray-600 text-center mt-2">
                  Skattereduktion abolished from 2026-01-01
                </p>
              </>
            )}
            <p className="text-xs text-gray-700 text-center mt-1">
              Annual estimate = this month &times; 12 (seasonal variation not
              included)
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
