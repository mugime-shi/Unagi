import { useState, type FormEvent } from "react";
import { useSimulate } from "../hooks/useSimulate";
import { formatPrice, PRICE_UNIT } from "../utils/formatters";

interface ResultCardProps {
  label: string;
  cost: number;
  savings?: number;
}

function ResultCard({ label, cost, savings }: ResultCardProps) {
  const savingsColor =
    savings === undefined
      ? ""
      : savings >= 0
        ? "text-cyan-600 dark:text-cyan-400"
        : "text-orange-600 dark:text-orange-400";

  return (
    <div className="bg-surface-secondary rounded-xl p-3 text-center">
      <p className="text-xs text-content-secondary mb-1 leading-tight">
        {label}
      </p>
      <p className="text-lg font-semibold text-content-primary">
        {cost.toFixed(0)}
      </p>
      <p className="text-xs text-content-muted">SEK/mo</p>
      {savings !== undefined && (
        <p className={`text-xs mt-1 font-medium ${savingsColor}`}>
          {savings >= 0 ? "\u2212" : "+"}
          {Math.abs(savings).toFixed(0)} SEK
        </p>
      )}
    </div>
  );
}

export function ConsumptionSimulator() {
  const [kwh, setKwh] = useState<string>("500");
  const [fixedPrice, setFixedPrice] = useState<string>("1.80");
  const { result, loading, error, run } = useSimulate();

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    run({
      monthly_kwh: parseFloat(kwh),
      fixed_price_sek_kwh: parseFloat(fixedPrice),
    });
  };

  return (
    <div className="bg-surface-primary rounded-2xl p-4">
      <h2 className="text-sm font-medium text-content-primary mb-1">
        Monthly cost comparison
      </h2>
      <p className="text-xs text-content-faint mb-3">
        Fixed contract vs dynamic (spot) pricing
      </p>

      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap gap-3 mb-4 items-end"
      >
        <div className="flex flex-col gap-1">
          <label className="text-xs text-content-secondary">
            Monthly usage
          </label>
          <div className="relative">
            <input
              type="number"
              value={kwh}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setKwh(e.target.value)
              }
              className="bg-surface-secondary border border-surface-tertiary text-content-primary rounded-lg px-3 py-1.5 text-sm w-28 pr-10"
              min="1"
              max="10000"
              step="1"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-content-muted">
              kWh
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-content-secondary">Fixed price</label>
          <div className="relative">
            <input
              type="number"
              value={fixedPrice}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setFixedPrice(e.target.value)
              }
              step="0.01"
              min="0.1"
              max="10"
              className="bg-surface-secondary border border-surface-tertiary text-content-primary rounded-lg px-3 py-1.5 text-sm w-28 pr-14"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-content-muted">
              SEK/kWh
            </span>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-sm transition-colors"
        >
          {loading ? "Calculating\u2026" : "Calculate"}
        </button>
      </form>

      {error && (
        <p className="text-red-400 text-xs mb-3">
          {error.message.includes("503") ||
          error.message.includes("No historical")
            ? "No price data in DB yet. Run backfill first."
            : error.message}
        </p>
      )}

      {result && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <ResultCard
              label="Fixed contract"
              cost={result.fixed.monthly_cost_sek}
            />
            {result.monthly_avg && (
              <ResultCard
                label="Gbg Energi (mo. avg)"
                cost={result.monthly_avg.monthly_cost_sek}
                savings={result.monthly_avg.savings_vs_fixed_sek}
              />
            )}
            <ResultCard
              label="Dynamic (no shift)"
              cost={result.dynamic.monthly_cost_sek}
              savings={result.dynamic.savings_vs_fixed_sek}
            />
            <ResultCard
              label="Dynamic + optimize"
              cost={result.optimized.monthly_cost_sek}
              savings={result.optimized.savings_vs_fixed_sek}
            />
          </div>
          {result.monthly_avg && (
            <p className="text-xs text-blue-600 dark:text-blue-400/80 text-center mb-1">
              This month&apos;s avg spot so far:{" "}
              {formatPrice(result.monthly_avg.avg_spot_sek_kwh)} {PRICE_UNIT} (
              {result.period?.month_days_with_data} days)
            </p>
          )}
          <p className="text-xs text-content-faint text-center">
            Based on {result.period?.days_with_data} days of SE3 real prices ·{" "}
            avg spot {formatPrice(result.dynamic.avg_spot_sek_kwh)} {PRICE_UNIT}
          </p>
        </>
      )}
    </div>
  );
}
