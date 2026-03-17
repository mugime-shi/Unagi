# Namazu — Swedish Electricity Price Dashboard

**Live demo → [namazu-el.vercel.app](https://namazu-el.vercel.app)**

A real-time dashboard for SE3 (Göteborg) electricity spot prices, built to answer one practical question: *when should you run your dishwasher?*

---

## What it does

**Prices** — real-time market data & forecasts
- Today's and tomorrow's spot prices (15-min slots, ENTSO-E data)
- Current price level indicator — cheap / normal / expensive vs daily average
- Best time to run washing machine (2h), dishwasher (2h), EV charging (4h)
- **Review mode** — browse any past date and overlay actual prices with ML predictions (LightGBM + Weekday Avg), with per-day MAE

**Simulators** — what-if planning tools
- Monthly cost comparison: fixed contract vs dynamic (spot) vs Göteborg Energi monthly-average
- Solar PV generation estimate using real SMHI irradiance data (Göteborg Sol station)
- Revenue breakdown: self-consumption savings / grid export income / battery effect
- Side-by-side tax credit comparison (≤2025 scheme vs 2026+ after Sweden abolished the deduction)

---

## Why I built this

In Japan I worked on a Solar Power Retails system where utilities pay a government-fixed price for all solar generation — straightforward, no optimization needed. Sweden works differently: you sell at the real-time spot price and buy at the same spot price, so *when* you consume or export matters. This project is my way of understanding that market by building something useful for my own apartment in Göteborg.

---

## Screenshot

<!-- Add a dashboard screenshot here: docs/screenshot.png -->
![Namazu dashboard](docs/screenshot.png)

---

## Quick start (local)

```bash
git clone git@github.com:mugime-shi/Namazu.git
cd Namazu
docker compose up          # FastAPI on :8100, PostgreSQL on :5533
cd frontend && npm install && npm run dev   # React on :5173
```

`localhost:5173` → dashboard with mock data (no API key needed for basic browsing).

To fetch real prices, add a free [ENTSO-E API key](https://transparency.entsoe.eu/) to `backend/.env`:

```
DATABASE_URL=postgresql://postgres:password@localhost:5533/namazu
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

112 tests across unit and integration layers — price parsing, timezone/DST handling, solar simulation, push subscriptions, and API client edge cases (network errors, empty windows, HTTP error codes).

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  React + Tailwind CSS  (Vercel)              │
│  Prices │ History │ Simulators (Cost + Solar) │
└────────────────────┬─────────────────────────┘
                     │ /api/*  (Vercel rewrite proxy)
                     ▼
┌──────────────────────────────────────────────┐
│  AWS API Gateway  →  Lambda (arm64 Docker)   │
│  FastAPI + Mangum                            │
│  /prices  │  /simulate  │  /solar            │
│                                              │
│  EventBridge cron (13:30 CET daily)          │
│  → Scheduler Lambda → ENTSO-E fetch          │
└──────┬───────────┬──────────────────┬────────┘
       ▼           ▼                  ▼
  ENTSO-E API   SMHI API        PostgreSQL
  (spot price)  (irradiance)    (Supabase)
```

**Infrastructure managed by Terraform** — ECR, Lambda × 2, API Gateway, EventBridge, IAM.

**CI/CD via GitHub Actions** — `git push main` → pytest → arm64 Docker build → ECR push → Lambda update → smoke test.

---

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI | Auto-docs (Swagger), Pydantic types, async-ready |
| Runtime | AWS Lambda (arm64 Docker) | Zero cost at this scale; same app code runs locally (dev target) and in Lambda |
| ASGI adapter | Mangum | Wraps FastAPI for Lambda without modifying app code |
| Database | PostgreSQL on Supabase | Full SQL, free tier with no 12-month expiry (unlike RDS) |
| Frontend | React 19, Vite, Tailwind CSS | Fast iteration; Recharts for time-series visualization |
| Hosting | Vercel | Free, auto-deploy on push |
| IaC | Terraform | Declarative, reproducible, cloud-agnostic |
| CI/CD | GitHub Actions | test → build → deploy on every push to main |
| Data sources | ENTSO-E Transparency Platform, SMHI Open Data | Official public APIs, no cost |

---

## API

The backend is a standard FastAPI app (Swagger UI is disabled in production).

Key endpoints:

```
GET  /api/v1/prices/today                         → today's 15-min spot prices
GET  /api/v1/prices/tomorrow                      → tomorrow's prices (available after 13:00 CET)
GET  /api/v1/prices/range?start=...&end=...       → prices for arbitrary date range (max 30 days)
GET  /api/v1/prices/cheapest-hours?duration=2     → cheapest consecutive window
GET  /api/v1/prices/forecast?model=lgbm           → ML forecast (LightGBM or same_weekday_avg)
GET  /api/v1/prices/forecast/accuracy?days=30     → per-model MAE/RMSE over N days
GET  /api/v1/prices/forecast/retrospective?date=… → predictions vs actuals for a past date
POST /api/v1/simulate/consumption                 → fixed vs dynamic cost comparison
POST /api/v1/simulate/solar                       → PV generation + revenue estimate
GET  /health                                      → service health check
```

---

## Cost

Everything runs on permanent free tiers — no 12-month expiry.

| Resource | Service | Cost |
|---|---|---|
| Backend | Lambda (1M req/month free) | 0 SEK |
| Routing | API Gateway (1M calls/month free) | 0 SEK |
| Scheduler | EventBridge | 0 SEK |
| Frontend | Vercel | 0 SEK |
| Database | Supabase (500 MB, no expiry) | 0 SEK |
| Data | ENTSO-E + SMHI (open APIs) | 0 SEK |

---

## Project structure

```
Namazu/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI entry point + Mangum handler
│       ├── routers/             # prices, simulate, solar
│       ├── services/            # entsoe_client, smhi_client, solar_model
│       ├── db/                  # SQLAlchemy models + Alembic migrations
│       └── tasks/fetch_prices.py  # EventBridge scheduler handler
├── frontend/
│   └── src/
│       ├── components/          # PriceChart, CheapHoursWidget, SolarSimulator…
│       └── hooks/               # usePrices, useSolar
├── infra/                       # Terraform (Lambda, API GW, EventBridge, ECR, IAM)
├── Dockerfile                   # Multi-stage: dev / lambda / scheduler
├── docker-compose.yml           # Local dev: FastAPI + PostgreSQL
└── .github/workflows/deploy.yml # CI/CD pipeline
```

---

## Contact

mugimeishi@gmail.com
