// ─── Common ───────────────────────────────────────────────────────────────────

export type Area = "SE1" | "SE2" | "SE3" | "SE4";
export type Tab = "today" | "tomorrow" | "trends";
export type Layer = "prices" | "simulators" | "cost";

export interface AreaInfo {
  id: Area;
  label: string;
  city: string;
  cities: string;
}

// ─── Prices ───────────────────────────────────────────────────────────────────

export interface PricePoint {
  timestamp_utc: string;
  price_sek_kwh: number;
  price_eur_mwh: number;
  resolution?: string;
  is_estimate?: boolean;
}

export interface PriceSummary {
  min_sek_kwh: number;
  avg_sek_kwh: number;
  max_sek_kwh: number;
  month_avg_sek_kwh?: number | null;
}

export interface PricesResponse {
  date: string;
  area: string;
  currency?: string;
  count: number;
  is_estimate: boolean;
  published?: boolean;
  summary: PriceSummary;
  prices: PricePoint[];
}

// ─── Balancing ────────────────────────────────────────────────────────────────

export interface BalancingPrice {
  timestamp_utc: string;
  price_sek_kwh: number;
  price_eur_mwh: number;
  category?: string;
}

export interface BalancingResponse {
  date: string;
  area: string;
  count: number;
  short: BalancingPrice[];
  long: BalancingPrice[];
}

// ─── Generation ───────────────────────────────────────────────────────────────

export interface GenerationPoint {
  timestamp_utc: string;
  total_mw: number;
  renewable_pct?: number | null;
  carbon_intensity?: number | null;
  hydro?: number | null;
  wind?: number | null;
  nuclear?: number | null;
  solar?: number | null;
  fossil?: number | null;
  other?: number | null;
}

export interface GenerationResponse {
  area: string;
  date: string;
  time_series: GenerationPoint[];
}

// ─── Forecast ─────────────────────────────────────────────────────────────────

export interface ForecastSlot {
  hour: number;
  avg_sek_kwh: number | null;
  low_sek_kwh?: number | null;
  high_sek_kwh?: number | null;
  timestamp_utc?: string;
}

export interface ForecastResponse {
  date: string;
  area: string;
  slots: ForecastSlot[];
}

// ─── LGBM Forecast ────────────────────────────────────────────────────────────

export interface ShapFeature {
  group: string;
  impact: number;
}

export interface ShapHour {
  hour: number;
  top: ShapFeature[];
}

export interface ShapExplanations {
  hours: ShapHour[];
}

export interface LgbmForecastResponse {
  date: string;
  area: string;
  slots: ForecastSlot[];
  explanations?: ShapExplanations;
}

// ─── Retrospective ────────────────────────────────────────────────────────────

export interface RetrospectiveEntry {
  hour: number;
  predicted_sek_kwh: number | null;
  predicted_low_sek_kwh?: number | null;
  predicted_high_sek_kwh?: number | null;
  actual_sek_kwh: number | null;
  timestamp_utc?: string;
}

export interface RetrospectiveResponse {
  date: string;
  area: string;
  predicted_at: string | null;
  models: Record<string, RetrospectiveEntry[]>;
  shap_explanations?: ShapExplanations | null;
}

// ─── Weekly Forecast ──────────────────────────────────────────────────────────

export interface WeeklyDay {
  date: string;
  daily_low: number;
  daily_avg: number;
  daily_high: number;
  confidence?: number;
  slots: ForecastSlot[];
}

export interface WeeklyForecastResponse {
  area: string;
  forecast_date: string;
  thirty_day_avg?: number;
  days: WeeklyDay[];
}

/** Response from GET /prices/forecast/weekly (includes classification) */
export interface WeeklyDayClassified {
  date: string;
  weekday: string;
  horizon: number;
  model: string;
  daily_avg: number;
  daily_low: number;
  daily_high: number;
  classification: "cheap" | "normal" | "expensive";
  confidence: number;
  slots: ForecastSlot[];
}

export interface WeeklyClassifiedResponse {
  area: string;
  generated_at: string;
  reference_avg_30d: number | null;
  days: WeeklyDayClassified[];
}

// ─── Forecast Accuracy ────────────────────────────────────────────────────────

export interface ModelAccuracy {
  mae: number;
  rmse?: number;
  total_samples: number;
  days_included?: number;
  last_updated?: string;
}

export interface ForecastAccuracyResponse {
  area: string;
  days_included: number;
  models: Record<string, ModelAccuracy>;
  coverage?: {
    nominal: number;
    actual: number;
    samples: number;
  };
}

export interface BreakdownBucket {
  bucket: string | number;
  mae: number;
  rmse?: number;
  samples: number;
}

export interface ForecastBreakdownResponse {
  area: string;
  days: number;
  breakdown_by: string;
  models: Record<string, BreakdownBucket[]>;
}

// ─── History ──────────────────────────────────────────────────────────────────

export interface HistoryDay {
  date: string;
  avg_sek_kwh: number | null;
  min_sek_kwh?: number | null;
  max_sek_kwh?: number | null;
}

export interface HistoryResponse {
  area: string;
  days_requested: number;
  daily: HistoryDay[];
}

// ─── Multi-Zone ───────────────────────────────────────────────────────────────

export interface ZoneDaily {
  date: string;
  avg_sek_kwh: number;
}

export interface MultiZoneResponse {
  days_included: number;
  zones: Record<string, ZoneDaily[]>;
}

// ─── Cheap Hours ──────────────────────────────────────────────────────────────

export interface CheapWindow {
  start_hour_utc: string;
  duration_hours: number;
  avg_sek_kwh: number;
  slots: { hour_utc: string; avg_sek_kwh: number }[];
}

export interface CheapHoursResponse {
  date: string;
  area: string;
  appliances: {
    name: string;
    icon: string;
    duration_hours: number;
    best_window: CheapWindow;
  }[];
}

/** Response from GET /prices/cheapest-hours (single duration query) */
export interface CheapestWindowResponse {
  area: string;
  date: string;
  currency: string;
  is_estimate: boolean;
  cheapest_window: {
    start_utc: string;
    end_utc: string;
    duration_hours: number;
    avg_sek_kwh: number;
    slots: { hour_utc: string; avg_sek_kwh: number }[];
  };
}

// ─── Simulation ───────────────────────────────────────────────────────────────

export interface ConsumptionResult {
  fixed_cost_sek: number;
  spot_cost_sek: number;
  optimal_cost_sek: number;
  fixed_price_sek_kwh: number;
  monthly_kwh: number;
  savings_vs_fixed_sek: number;
  savings_vs_fixed_pct: number;
  optimal_savings_vs_spot_sek: number;
  optimal_savings_vs_spot_pct: number;
  hourly: {
    hour: string;
    price_sek_kwh: number;
    consumption_kwh: number;
    cost_sek: number;
  }[];
}

/** Response from POST /simulate/consumption */
export interface SimulationResponse {
  monthly_kwh: number;
  fixed: {
    price_per_kwh_sek: number;
    monthly_cost_sek: number;
  };
  dynamic: {
    avg_spot_sek_kwh: number;
    total_per_kwh_sek: number;
    monthly_cost_sek: number;
    savings_vs_fixed_sek: number;
    savings_pct: number;
  };
  optimized: {
    description: string;
    avg_spot_sek_kwh: number;
    total_per_kwh_sek: number;
    monthly_cost_sek: number;
    savings_vs_fixed_sek: number;
    savings_pct: number;
  };
  monthly_avg?: {
    avg_spot_sek_kwh: number;
    total_per_kwh_sek: number;
    monthly_cost_sek: number;
    savings_vs_fixed_sek: number;
    savings_pct: number;
  };
  period?: {
    start: string;
    end: string;
    days_with_data: number;
    price_slots: number;
    month_start: string;
    month_days_with_data: number;
  };
}

export interface SolarResult {
  total_kwh: number;
  revenue_sell_sek: number;
  revenue_self_sek: number;
  total_revenue_sek: number;
  avg_sell_price: number;
  peak_kw: number;
  hourly: {
    hour: string;
    generation_kwh: number;
    price_sek_kwh: number;
    revenue_sek: number;
    irradiance_w_m2: number;
  }[];
}

// ─── Notification ─────────────────────────────────────────────────────────────

export type NotificationStatus =
  | "loading"
  | "unsupported"
  | "idle"
  | "subscribed"
  | "denied"
  | "error";

// ─── Monthly Averages ────────────────────────────────────────────────────────

export interface MonthlyAvg {
  month: string;
  avg_sek_kwh: number;
  count: number;
}

export interface MonthlyAvgResponse {
  area: string;
  months: MonthlyAvg[];
}

// ─── Chart Data (enriched in PriceChart) ──────────────────────────────────────

export interface ChartDataPoint {
  hour: string;
  price_sek_kwh: number;
  price_eur_mwh: number;
  is_estimate?: boolean;
  forecast_low: number | null;
  forecast_band: number | null;
  forecast_avg: number | null;
  forecast_top: number | null;
  lgbm_forecast: number | null;
  lgbm_low: number | null;
  lgbm_band: number | null;
  lgbm_top: number | null;
  imb_short: number | null;
  imb_long: number | null;
  retro_lgbm: number | null;
  retro_weekday: number | null;
  shap_top: ShapFeature[] | null;
  timestamp_utc?: string;
}
