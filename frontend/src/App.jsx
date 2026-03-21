import { useState } from "react";
import { CheapHoursWidget } from "./components/CheapHoursWidget";
import { ForecastAccuracy } from "./components/ForecastAccuracy";
import { GenerationChart } from "./components/GenerationChart";
import { NotificationBell } from "./components/NotificationBell";
import { PriceChart } from "./components/PriceChart";
import { PriceHistory } from "./components/PriceHistory";
import { PriceIndicator } from "./components/PriceIndicator";
import { ConsumptionSimulator } from "./components/ConsumptionSimulator";
import { SolarSimulator } from "./components/SolarSimulator";
import { useBalancing } from "./hooks/useBalancing";
import { useDatePrices } from "./hooks/useDatePrices";
import { useForecast } from "./hooks/useForecast";
import { useGeneration } from "./hooks/useGeneration";
import { useGenerationDate } from "./hooks/useGenerationDate";
import { useRetrospective } from "./hooks/useRetrospective";
import { usePrices } from "./hooks/usePrices";
import { dateWithWeekday } from "./utils/formatters";

const AREAS = [
  { id: "SE1", label: "SE1", city: "Luleå" },
  { id: "SE2", label: "SE2", city: "Sundsvall" },
  { id: "SE3", label: "SE3", city: "Göteborg" },
  { id: "SE4", label: "SE4", city: "Malmö" },
];

function todayISO() {
  return new Date().toISOString().split("T")[0];
}

function tomorrowISO() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

export default function App() {
  const [layer, setLayer] = useState("prices");
  const [tab, setTab] = useState("now"); // "now" | "forecast"
  const [forecastDate, setForecastDate] = useState(tomorrowISO);
  const [area, setArea] = useState("SE3");

  const isTomorrow = forecastDate === tomorrowISO();
  const isPastDate = forecastDate < todayISO();

  // ── Today data ──
  const {
    data: todayData,
    loading: todayLoading,
    error: todayError,
  } = usePrices("today", area);
  const { data: balancing } = useBalancing(todayISO(), area);
  const { data: generation } = useGeneration(area);

  // ── Forecast tab data ──
  // Tomorrow prices via usePrices; past dates via useDatePrices
  const {
    data: tomorrowData,
    loading: tomorrowLoading,
    error: tomorrowError,
  } = usePrices(tab === "forecast" && isTomorrow ? "tomorrow" : null, area);
  const {
    data: pastData,
    loading: pastLoading,
    error: pastError,
  } = useDatePrices(
    tab === "forecast" && !isTomorrow ? forecastDate : null,
    area,
  );

  const { data: forecast } = useForecast(
    tab === "forecast" ? forecastDate : null,
    area,
  );
  const { data: retrospective } = useRetrospective(
    tab === "forecast" ? forecastDate : null,
    area,
  );
  const { data: forecastGeneration } = useGenerationDate(
    tab === "forecast" && isPastDate ? forecastDate : null,
    area,
  );

  // Extract LGBM forecast (center line + 80% CI band) from retrospective — tomorrow and past dates
  const lgbmForecast = retrospective?.models?.lgbm
    ? {
        slots: retrospective.models.lgbm.map((p) => ({
          hour: p.hour,
          avg_sek_kwh: p.predicted_sek_kwh,
          low_sek_kwh: p.predicted_low_sek_kwh ?? null,
          high_sek_kwh: p.predicted_high_sek_kwh ?? null,
        })),
      }
    : null;

  // Resolved forecast tab price data
  const forecastPriceData = isTomorrow ? tomorrowData : pastData;
  const forecastLoading = isTomorrow ? tomorrowLoading : pastLoading;
  const forecastError = isTomorrow ? tomorrowError : pastError;

  const areaCity = AREAS.find((a) => a.id === area)?.city ?? area;

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-4 sm:px-6 py-4 flex items-center gap-3">
        <span className="text-xl font-bold tracking-tight">Namazu</span>

        {/* Layer selector */}
        <nav className="ml-auto flex gap-1">
          {[
            { id: "prices", label: "Prices" },
            { id: "history", label: "History" },
            { id: "simulators", label: "Simulators" },
          ].map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setLayer(id)}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                layer === id
                  ? "bg-gray-700 text-white"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>

        <NotificationBell area={area} />
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-4">
        {/* Area selector — global, visible on all layers */}
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {AREAS.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setArea(id)}
                className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                  area === id
                    ? "bg-sky-600 text-white"
                    : "text-gray-500 hover:text-gray-300 border border-gray-700"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="text-gray-500 text-sm">· {areaCity}</span>
        </div>

        {/* ── Layer 1: Prices ── */}
        {layer === "prices" && (
          <>
            {/* Tab selector */}
            <div className="flex gap-2 items-center">
              {[
                { id: "now", label: "Now" },
                { id: "forecast", label: "Forecast" },
              ].map(({ id, label }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                    tab === id
                      ? "bg-sky-600 text-white"
                      : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                  }`}
                >
                  {label}
                </button>
              ))}

              {/* Forecast tab: date navigation */}
              {tab === "forecast" && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      const d = new Date(forecastDate);
                      d.setDate(d.getDate() - 1);
                      setForecastDate(d.toISOString().split("T")[0]);
                    }}
                    className="px-2 py-1 rounded-lg bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm"
                  >
                    &larr;
                  </button>
                  <div className="relative">
                    <input
                      type="date"
                      value={forecastDate}
                      max={tomorrowISO()}
                      onChange={(e) => setForecastDate(e.target.value)}
                      className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
                    />
                    <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm text-gray-300 pointer-events-none flex items-center gap-2">
                      <span>
                        {forecastDate}{" "}
                        <span className="text-gray-500">
                          (
                          {new Date(
                            forecastDate + "T12:00:00",
                          ).toLocaleDateString("en-SE", { weekday: "short" })}
                          )
                        </span>
                      </span>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="w-4 h-4 text-gray-500 shrink-0"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={1.5}
                          d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                        />
                      </svg>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      const d = new Date(forecastDate);
                      d.setDate(d.getDate() + 1);
                      const next = d.toISOString().split("T")[0];
                      if (next <= tomorrowISO()) setForecastDate(next);
                    }}
                    disabled={forecastDate >= tomorrowISO()}
                    className="px-2 py-1 rounded-lg bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm disabled:opacity-30 disabled:pointer-events-none"
                  >
                    &rarr;
                  </button>
                </div>
              )}
            </div>

            {/* ── Today tab ── */}
            {tab === "now" && (
              <>
                {todayLoading && (
                  <div className="animate-pulse space-y-4">
                    <div className="bg-gray-900 rounded-2xl p-4">
                      <div className="flex items-center justify-between mb-4">
                        <div className="h-4 bg-gray-700 rounded w-40" />
                        <div className="h-3 bg-gray-700 rounded w-12" />
                      </div>
                      <div className="h-[300px] bg-gray-800 rounded-xl" />
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      {[0, 1, 2, 3].map((i) => (
                        <div
                          key={i}
                          className="bg-gray-900 rounded-xl py-3 px-4 space-y-2"
                        >
                          <div className="h-3 bg-gray-700 rounded w-16 mx-auto" />
                          <div className="h-6 bg-gray-700 rounded w-12 mx-auto" />
                          <div className="h-3 bg-gray-700 rounded w-10 mx-auto" />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {todayError && (
                  <p className="text-red-400 text-sm">
                    Failed to load prices: {todayError.message}
                  </p>
                )}

                {todayData && (
                  <>
                    <PriceIndicator prices={todayData.prices} />

                    {/* Price + Generation visual group */}
                    <div className="space-y-2">
                      <div className="bg-gray-900 rounded-2xl p-4">
                        <div className="flex items-center justify-between mb-4">
                          <div>
                            <h2 className="text-sm font-medium text-gray-300">
                              Spot price — {dateWithWeekday(todayData.date)} ·{" "}
                              {todayData.count} slots
                            </h2>
                            {balancing && (
                              <p className="text-xs text-gray-500 mt-0.5">
                                + Imbalance prices (eSett EXP14) ·{" "}
                                {balancing.count} pts
                              </p>
                            )}
                          </div>
                          <span className="text-xs text-gray-500">SEK/kWh</span>
                        </div>
                        <PriceChart
                          prices={todayData.prices}
                          isEstimate={todayData.is_estimate}
                          balancing={balancing}
                          showNowMarker={true}
                        />
                      </div>

                      {generation?.time_series?.length > 0 && (
                        <GenerationChart
                          generation={generation}
                          prices={todayData.prices}
                        />
                      )}
                    </div>

                    {/* Min / Avg (date) / Avg (month) / Max */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                      {[
                        { label: "Min", value: todayData.summary.min_sek_kwh },
                        {
                          label: `Avg (${todayData.date})`,
                          value: todayData.summary.avg_sek_kwh,
                        },
                        {
                          label: "Avg (month)",
                          value: todayData.summary.month_avg_sek_kwh,
                        },
                        { label: "Max", value: todayData.summary.max_sek_kwh },
                      ].map(({ label, value }) => (
                        <div
                          key={label}
                          className="bg-gray-900 rounded-xl py-3"
                        >
                          <p className="text-xs text-gray-500 mb-1">{label}</p>
                          <p className="text-lg font-semibold">
                            {value != null ? value.toFixed(2) : "—"}
                          </p>
                          <p className="text-xs text-gray-500">SEK/kWh</p>
                        </div>
                      ))}
                    </div>

                    <CheapHoursWidget date={todayISO()} area={area} />
                  </>
                )}
              </>
            )}

            {/* ── Forecast tab ── */}
            {tab === "forecast" && (
              <>
                {forecastLoading && (
                  <div className="animate-pulse bg-gray-900 rounded-2xl p-4">
                    <div className="h-[300px] bg-gray-800 rounded-xl" />
                  </div>
                )}
                {forecastError && (
                  <p className="text-red-400 text-sm">
                    Failed to load prices: {forecastError.message}
                  </p>
                )}

                {forecastPriceData && (
                  <>
                    {/* Unpublished banner */}
                    {isTomorrow &&
                      forecastPriceData.is_estimate &&
                      forecastPriceData.published === false && (
                        <p className="text-yellow-400 text-xs text-center bg-yellow-400/10 rounded-lg py-2 px-3">
                          Tomorrow&apos;s prices are typically published after
                          13:00 CET
                        </p>
                      )}

                    <div className="bg-gray-900 rounded-2xl p-4">
                      <div className="flex items-center justify-between mb-4">
                        <div>
                          <h2 className="text-sm font-medium text-gray-300">
                            {isTomorrow ? "Forecast" : "Spot price"} —{" "}
                            {dateWithWeekday(forecastPriceData.date)} ·{" "}
                            {forecastPriceData.count} slots
                          </h2>
                          {retrospective?.models &&
                            Object.keys(retrospective.models).length > 0 && (
                              <p className="text-xs text-gray-500 mt-0.5">
                                + Forecast predictions overlay
                              </p>
                            )}
                        </div>
                        <span className="text-xs text-gray-500">SEK/kWh</span>
                      </div>
                      <PriceChart
                        prices={forecastPriceData.prices}
                        isEstimate={forecastPriceData.is_estimate}
                        forecast={forecast}
                        lgbmForecast={lgbmForecast}
                        retrospective={retrospective}
                        defaultShowLgbm={true}
                        defaultShowWeekdayAvg={false}
                        predictedAt={
                          isTomorrow ? retrospective?.predicted_at : null
                        }
                        showNowMarker={false}
                      />
                    </div>

                    {/* Generation mix — past dates only */}
                    {forecastGeneration?.time_series?.length > 0 && (
                      <GenerationChart
                        generation={forecastGeneration}
                        prices={forecastPriceData.prices}
                      />
                    )}

                    {/* Summary cards */}
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-center">
                      {[
                        {
                          label: "Min",
                          value: forecastPriceData.summary.min_sek_kwh,
                        },
                        {
                          label: "Avg",
                          value: forecastPriceData.summary.avg_sek_kwh,
                        },
                        {
                          label: "Max",
                          value: forecastPriceData.summary.max_sek_kwh,
                        },
                      ].map(({ label, value }) => (
                        <div
                          key={label}
                          className="bg-gray-900 rounded-xl py-3"
                        >
                          <p className="text-xs text-gray-500 mb-1">{label}</p>
                          <p className="text-lg font-semibold">
                            {value != null ? value.toFixed(2) : "—"}
                          </p>
                          <p className="text-xs text-gray-500">SEK/kWh</p>
                        </div>
                      ))}
                    </div>

                    {/* Forecast accuracy — cumulative 30-day MAE */}
                    <ForecastAccuracy area={area} />

                    {/* Per-date accuracy — past dates only */}
                    {isPastDate &&
                      retrospective?.models &&
                      Object.keys(retrospective.models).length > 0 && (
                        <div className="bg-gray-900 rounded-xl p-4">
                          <h3 className="text-xs text-gray-500 mb-3">
                            Prediction accuracy — {forecastPriceData.date}
                          </h3>
                          <div className="space-y-2">
                            {Object.entries(retrospective.models)
                              .map(([model, entries]) => {
                                const pairs = entries.filter(
                                  (e) =>
                                    e.predicted_sek_kwh != null &&
                                    e.actual_sek_kwh != null,
                                );
                                const mae =
                                  pairs.length > 0
                                    ? pairs.reduce(
                                        (s, e) =>
                                          s +
                                          Math.abs(
                                            e.predicted_sek_kwh -
                                              e.actual_sek_kwh,
                                          ),
                                        0,
                                      ) / pairs.length
                                    : Infinity;
                                return { model, pairs, mae };
                              })
                              .filter(({ pairs }) => pairs.length > 0)
                              .sort((a, b) => a.mae - b.mae)
                              .map(({ model, pairs, mae }) => (
                                <div
                                  key={model}
                                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800"
                                >
                                  <span className="text-sm font-medium text-gray-200">
                                    {model === "same_weekday_avg"
                                      ? "Weekday Avg"
                                      : model.toUpperCase()}
                                  </span>
                                  <span className="text-sm text-gray-300">
                                    MAE {mae.toFixed(2)} SEK/kWh ·{" "}
                                    {pairs.length} hrs
                                  </span>
                                </div>
                              ))}
                          </div>
                        </div>
                      )}
                  </>
                )}

                {!forecastLoading && !forecastError && !forecastPriceData && (
                  <p className="text-gray-500 text-sm text-center py-8">
                    No price data available for this date
                  </p>
                )}
              </>
            )}
          </>
        )}

        {/* ── History ── */}
        {layer === "history" && <PriceHistory area={area} />}

        {/* ── Simulators ── */}
        {layer === "simulators" && (
          <div className="space-y-6">
            <ConsumptionSimulator />
            <SolarSimulator />
          </div>
        )}
      </main>
    </div>
  );
}
