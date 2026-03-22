import { useState } from "react";
import { useSimulate } from "../hooks/useSimulate";

function ResultCard({ label, cost, savings }) {
  const savingsColor =
    savings === undefined
      ? ""
      : savings >= 0
        ? "text-cyan-400"
        : "text-orange-400";

  return (
    <div className="bg-sea-800 rounded-xl p-3 text-center">
      <p className="text-xs text-gray-400 mb-1 leading-tight">{label}</p>
      <p className="text-lg font-semibold">{cost.toFixed(0)}</p>
      <p className="text-xs text-gray-500">SEK/mo</p>
      {savings !== undefined && (
        <p className={`text-xs mt-1 font-medium ${savingsColor}`}>
          {savings >= 0 ? "−" : "+"}
          {Math.abs(savings).toFixed(0)} SEK
        </p>
      )}
    </div>
  );
}

export function ConsumptionSimulator() {
  const [kwh, setKwh] = useState("500");
  const [fixedPrice, setFixedPrice] = useState("1.80");
  const { result, loading, error, run } = useSimulate();

  const handleSubmit = (e) => {
    e.preventDefault();
    run({
      monthly_kwh: parseFloat(kwh),
      fixed_price_sek_kwh: parseFloat(fixedPrice),
    });
  };

  return (
    <div className="bg-sea-900 rounded-2xl p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-1">
        Monthly cost comparison
      </h2>
      <p className="text-xs text-gray-600 mb-3">
        Fixed contract vs dynamic (spot) pricing
      </p>

      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap gap-3 mb-4 items-end"
      >
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-400">Monthly usage</label>
          <div className="relative">
            <input
              type="number"
              value={kwh}
              onChange={(e) => setKwh(e.target.value)}
              className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-1.5 text-sm w-28 pr-10"
              min="1"
              max="10000"
              step="1"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500">
              kWh
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-400">Fixed price</label>
          <div className="relative">
            <input
              type="number"
              value={fixedPrice}
              onChange={(e) => setFixedPrice(e.target.value)}
              step="0.01"
              min="0.1"
              max="10"
              className="bg-sea-800 border border-sea-700 rounded-lg px-3 py-1.5 text-sm w-28 pr-14"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500">
              SEK/kWh
            </span>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-sm transition-colors"
        >
          {loading ? "Calculating…" : "Calculate"}
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
            <p className="text-xs text-blue-400/80 text-center mb-1">
              This month&apos;s avg spot so far:{" "}
              {result.monthly_avg.avg_spot_sek_kwh.toFixed(2)} SEK/kWh (
              {result.period?.month_days_with_data} days)
            </p>
          )}
          <p className="text-xs text-gray-600 text-center">
            Based on {result.period?.days_with_data} days of SE3 real prices ·{" "}
            avg spot {result.dynamic.avg_spot_sek_kwh.toFixed(2)} SEK/kWh
          </p>
        </>
      )}
    </div>
  );
}
