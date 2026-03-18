# Namazu — Swedish Electricity Price Dashboard

> *Namazu (鯰) — the mythical Japanese catfish said to sense earthquakes before they happen. This one senses price movements before they spike.*

**[Live demo → namazu-el.vercel.app](https://namazu-el.vercel.app)** &nbsp;|&nbsp; 142 tests passing &nbsp;|&nbsp; 0 SEK/month

A real-time dashboard for Swedish electricity spot prices with ML forecasting, built to answer one practical question: *when should you run your dishwasher?*

---

## What it does

### Real-time prices
- Today's and tomorrow's spot prices — 15-min slots from ENTSO-E, updated daily via EventBridge cron
- Current price level indicator (cheap / normal / expensive) with color + text for accessibility
- Best time recommendations: washing machine (2h), dishwasher (2h), EV charging (4h)
- Balancing prices overlay (eSett EXP14) — shows real-time grid stress vs day-ahead prediction

### ML price prediction
- **LightGBM** 24-hour forecast trained on 365 days of history (full seasonal cycle)
- **37 features** across 6 categories: calendar cycles, price lags (multi-day + 7d rolling mean/std), weather (temperature + solar radiation from SMHI/Open-Meteo), generation mix ratios, balancing price spreads, and interaction terms (wind×hour, temp×month)
- **Optuna-tuned hyperparameters** via 4-fold walk-forward cross-validation (100 trials)
- **46.3% MAE improvement** over same-weekday-average baseline (backtest: 720 samples, 30 days)
  - Phase 1: feature expansion (19→35) reduced MAE by 14.4%
  - Phase 2: Optuna tuning + quantile regression reduced MAE by another 5.5%
- **Quantile regression** prediction intervals (α=0.10/0.90) — asymmetric, calibrated confidence bands replacing naive ±1σ
- Same-weekday-average forecast with p10/p50/p90 uncertainty bands
- **Review mode**: browse any past date with prev/next buttons, overlay predictions vs actuals

### Energy analytics
- Generation mix stacked area chart — hydro / wind / nuclear / solar / other (ENTSO-E A75)
- Renewable % and carbon-free % badges with real-time update
- Multi-zone comparison (SE1–SE4 price spread over 90+ days)
- Price history with configurable trend window (7–365 days)

### Simulators
- Monthly cost comparison: fixed contract vs dynamic (spot) vs Göteborg Energi monthly-average
- Solar PV simulator with real SMHI irradiance data (Göteborg Sol station)
- Battery dispatch optimization (charge cheap, discharge expensive)
- Side-by-side tax credit comparison (≤2025 scheme vs 2026+ after Sweden abolished the 60 öre/kWh deduction)

### Monitoring & notifications
- Daily Telegram alert — tomorrow's avg/min/max, cheapest and priciest 2h windows
- Web Push notifications (VAPID) — browser alerts for next-day prices
- CloudWatch Alarms → SNS → alarm_handler Lambda → Telegram — automated failure alerting
- Dynamic EUR/SEK exchange rate from Riksbank API (daily cache, 11.0 fallback)

---

## Why I built this

In Japan I worked on a Solar Power Retails system where utilities pay a government-fixed price for all solar generation — straightforward, no optimization needed. Sweden works differently: you sell at the real-time spot price and buy at the same spot price, so *when* you consume or export matters.

The parallel is direct: Japan's FIT expiry in 2019 flipped the incentive from "sell everything" to "consume more, sell less." Sweden's tax credit abolition in 2026 triggers the same structural shift — through a different policy mechanism, but with the same backend design implications. This project is my way of understanding that market by building something useful for my own apartment in Göteborg.

---

## Quick start (local)

```bash
git clone git@github.com:mugime-shi/Namazu.git
cd Namazu
docker compose up          # FastAPI on :8100, PostgreSQL on :5533
cd frontend && npm install && npm run dev   # React on :5173
```

`localhost:5173` → dashboard with estimated data (no API key needed for basic browsing).

To fetch real prices, add a free [ENTSO-E API key](https://transparency.entsoe.eu/) to `backend/.env`:

```
DATABASE_URL=postgresql://namazu:namazu@localhost:5533/namazu
ENTSOE_API_KEY=your-key-here
```

Then backfill historical prices:

```bash
docker compose exec api python -m app.tasks.fetch_prices --backfill 30
```

---

## Testing

```bash
pip install -r backend/requirements-dev.txt
pytest backend/tests/ -v
```

142 tests across 10 test files — price parsing, timezone/DST handling (spring-forward 23h / fall-back 25h days), solar simulation, ENTSO-E/SMHI/eSett/Riksbank client mocks, push subscription management, LightGBM feature engineering, and forecast accuracy scoring.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  React 19 + Tailwind CSS  (Vercel)                   │
│  Prices │ History │ Simulators (Cost + Solar)         │
│  10 components  │  16 data hooks                     │
└──────────────────────┬───────────────────────────────┘
                       │ /api/*  (Vercel rewrite proxy)
                       ▼
┌──────────────────────────────────────────────────────┐
│  AWS API Gateway  →  Lambda (arm64 Docker)           │
│  FastAPI + Mangum   │   22 endpoints, 5 routers      │
│                                                      │
│  EventBridge cron (13:30 CET daily)                  │
│  → Scheduler Lambda → ENTSO-E + eSett + Riksbank     │
│                    → Telegram + Web Push alerts       │
│                    → LightGBM prediction recording    │
│                                                      │
│  CloudWatch Alarms → SNS → alarm_handler Lambda      │
│                           → Telegram failure alert    │
└───┬──────────┬──────────┬──────────┬─────────────────┘
    ▼          ▼          ▼          ▼
 ENTSO-E    SMHI       eSett    Riksbank    PostgreSQL
 (prices    (solar     (balance  (EUR/SEK)  (Supabase)
  + gen)    irrad.)    prices)
```

**Infrastructure managed by Terraform** — Lambda × 3, API Gateway, EventBridge, ECR × 2, CloudWatch Alarms × 2, SNS, IAM.

**CI/CD via GitHub Actions** — `git push main` → pytest → alembic migrate → arm64 Docker build → ECR push → Lambda update → smoke test.

---

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI | Auto-docs (Swagger), Pydantic types, async-ready |
| Runtime | AWS Lambda (arm64 Docker) | Zero cost at this scale; same image runs locally and in Lambda |
| ASGI adapter | Mangum | Wraps FastAPI for Lambda without modifying app code |
| Database | PostgreSQL on Supabase | Full SQL, free tier with no 12-month expiry (unlike RDS) |
| ML | LightGBM | Gradient boosting for tabular price prediction; fits Lambda's 512MB/30s constraints |
| Frontend | React 19, Vite, Tailwind CSS | Fast iteration; Recharts for time-series visualization |
| Hosting | Vercel | Free, auto-deploy on push |
| IaC | Terraform | Declarative, reproducible, cloud-agnostic |
| CI/CD | GitHub Actions | test → build → deploy on every push to main |
| Data | ENTSO-E, SMHI, eSett, Riksbank | Official public APIs, no cost |
| Monitoring | CloudWatch + SNS + Lambda → Telegram | Automated failure alerting pipeline |

---

## API

22 endpoints across 5 routers. Swagger UI available in development mode (`DEBUG=true`).

### Prices

```
GET  /api/v1/prices/today                              → today's 15-min spot prices
GET  /api/v1/prices/tomorrow                           → tomorrow's prices (after 13:00 CET)
GET  /api/v1/prices/range?start=...&end=...            → date range prices (max 30 days)
GET  /api/v1/prices/history?days=90                    → daily min/avg/max summaries
GET  /api/v1/prices/multi-zone?days=90                 → all 4 zones (SE1–SE4) daily averages
GET  /api/v1/prices/cheapest-hours?duration=2          → cheapest consecutive window
GET  /api/v1/prices/forecast?model=lgbm                → ML forecast (LightGBM or same_weekday_avg)
GET  /api/v1/prices/forecast/accuracy?days=30          → per-model MAE/RMSE
GET  /api/v1/prices/forecast/accuracy/breakdown?by=hour → accuracy by hour or weekday
GET  /api/v1/prices/forecast/retrospective?date=...    → predictions vs actuals for past date
GET  /api/v1/prices/balancing?date=...                 → imbalance prices (eSett)
GET  /api/v1/prices/exchange-rate                      → EUR/SEK from Riksbank
```

### Generation

```
GET  /api/v1/generation/today                          → today's generation mix (ENTSO-E A75)
GET  /api/v1/generation/date?date=...                  → historical generation data
```

### Simulation

```
POST /api/v1/simulate/consumption                      → fixed vs dynamic cost comparison
POST /api/v1/simulate/solar                            → PV generation + revenue estimate
```

### Notifications

```
GET    /api/v1/notify/vapid-public-key                 → VAPID key for browser push
POST   /api/v1/notify/subscribe                        → save push subscription
DELETE /api/v1/notify/subscribe                        → unsubscribe
```

### Health

```
GET  /health                                           → service liveness check
```

---

## Key metrics

| Metric | Value |
|---|---|
| Tests | 142 passing (10 test files) |
| API endpoints | 22 across 5 routers |
| External APIs | 4 (ENTSO-E, SMHI, eSett, Riksbank) |
| ML improvement | 46.3% MAE reduction vs baseline (0.44 → 0.24 SEK/kWh) |
| ML features | 37 (calendar, lags, weather, generation, balancing, interactions) |
| Training data | 365 days (full seasonal cycle) |
| UI components | 10 components, 16 data hooks |
| Infrastructure | 3 Lambdas, API GW, EventBridge, ECR × 2, CloudWatch × 2, SNS |
| Monthly cost | 0 SEK (all permanent free tiers) |

---

## Cost

Everything runs on permanent free tiers — no 12-month expiry.

| Resource | Service | Cost |
|---|---|---|
| Backend | Lambda (1M req/month free) | 0 SEK |
| Routing | API Gateway (1M calls/month free) | 0 SEK |
| Scheduler | EventBridge | 0 SEK |
| Monitoring | CloudWatch Alarms + SNS + alarm_handler Lambda | 0 SEK |
| Frontend | Vercel | 0 SEK |
| Database | Supabase (500 MB, no expiry) | 0 SEK |
| Data | ENTSO-E + SMHI + eSett + Riksbank (open APIs) | 0 SEK |

---

## Project structure

```
Namazu/
├── backend/
│   └── app/
│       ├── main.py                     # FastAPI + Mangum handler
│       ├── config.py                   # Pydantic settings
│       ├── routers/
│       │   ├── prices.py               # 12 price/forecast/balancing endpoints
│       │   ├── generation.py           # generation mix endpoints
│       │   ├── simulate.py             # consumption + solar simulation
│       │   ├── solar.py                # solar-specific routes
│       │   └── notify.py               # Web Push + Telegram
│       ├── services/
│       │   ├── entsoe_client.py        # ENTSO-E A44 (prices) + A75 (generation)
│       │   ├── smhi_client.py          # SMHI weather (radiation, temperature)
│       │   ├── esett_client.py         # eSett EXP14 balancing prices
│       │   ├── riksbank_client.py      # Riksbank EUR/SEK rate
│       │   ├── price_service.py        # price fetch/store/forecast
│       │   ├── generation_service.py   # generation mix processing
│       │   ├── balancing_service.py    # imbalance price handling
│       │   ├── ml_forecast_service.py  # LightGBM training + prediction
│       │   ├── feature_service.py      # ML feature engineering (37 features)
│       │   ├── backtest_service.py     # forecast accuracy tracking
│       │   ├── solar_model.py          # PV generation + optimization
│       │   ├── consumption_optimizer.py # cost comparison engine
│       │   ├── notify_service.py       # Web Push (VAPID)
│       │   └── telegram_service.py     # Telegram Bot alerts
│       ├── db/                         # SQLAlchemy models + Alembic migrations
│       └── tasks/fetch_prices.py       # EventBridge scheduler handler
├── frontend/
│   └── src/
│       ├── components/                 # 10 components (PriceChart, GenerationChart, …)
│       ├── hooks/                      # 16 data hooks (usePrices, useForecast, …)
│       └── utils/formatters.js         # CET/CEST timezone helpers
├── infra/                              # Terraform (8 .tf files + monitoring.tf)
├── Dockerfile                          # 5-stage: base / dev / lambda-base / lambda / scheduler
├── docker-compose.yml                  # Local dev: FastAPI + PostgreSQL
└── .github/workflows/deploy.yml        # CI/CD: pytest → build → deploy → smoke test
```

---

## Contact

mugimeishi@gmail.com
