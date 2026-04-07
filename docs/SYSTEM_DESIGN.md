# System Design

## Architecture overview

```
┌──────────────────────────────────────────────────────┐
│  React 19 + Tailwind CSS  (Vercel)                   │
│  Prices │ History │ Simulators (Cost + Solar)         │
│  11 components  │  18 data hooks                     │
└──────────────────────┬───────────────────────────────┘
                       │ /api/*  (Vercel rewrite proxy)
                       ▼
┌──────────────────────────────────────────────────────┐
│  AWS API Gateway  →  Lambda (arm64 Docker)           │
│  FastAPI + Mangum   │   22 endpoints, 5 routers      │
│                                                      │
│  EventBridge crons (Scheduler Lambda):                │
│    01:05 CET  Data collection                        │
│    01:20 CET  ML predictions (SHAP → DB)             │
│    05:05 CET  Nightly retry (idempotent)             │
│    13:30 CET  Price fetch + actuals + notifications   │
│    14:30/15:30/16:30 CET  Price retry (idempotent)   │
│                                                      │
│  CloudWatch Alarms → SNS → alarm_handler Lambda      │
│                           → Telegram failure alert    │
└───┬──────────┬──────────┬──────────┬─────────────────┘
    ▼          ▼          ▼          ▼
 ENTSO-E    SMHI       eSett    Riksbank    PostgreSQL
 (prices    (solar     (balance  (EUR/SEK)  (Supabase)
  + gen)    irrad.)    prices)
```

## Key design decisions

### Lambda + Docker (arm64)

Same Docker image runs locally (`docker compose up`) and in Lambda via Mangum. arm64 cuts cold-start time and cost vs x86. Three separate Lambdas: API handler, scheduler (EventBridge crons), and alarm handler (SNS → Telegram).

### Mangum as ASGI adapter

FastAPI stays framework-standard — no Lambda-specific code in routes or services. Mangum wraps the ASGI app at the handler level only. This means local dev, tests, and production all execute the same code paths.

### Supabase PostgreSQL over DynamoDB

Spot prices are inherently relational (time-series with zone/area dimensions, joins for forecast vs actuals). PostgreSQL's window functions and date arithmetic simplify queries that would require complex GSI designs in DynamoDB. Supabase's free tier has no 12-month expiry unlike AWS RDS.

### EventBridge scheduling strategy

Six cron windows reflect the ENTSO-E publication lifecycle:
- **01:05 CET** — Data collection (generation, balancing, load forecast, weather, gas).
- **01:20 CET** — ML predictions for tomorrow (d+1~d+7). SHAP explanations persisted to DB.
- **05:05 / 05:20 CET** — Idempotent retry for data + predictions.
- **13:30 CET** — Full pipeline: price fetch + actuals + notifications.
- **14:30, 15:30, 16:30 CET** — Price-only retry (no notifications). Covers Nord Pool delays.

All handlers are idempotent — re-running them is safe and expected. CET times shift +1h during CEST (summer).

### LightGBM for price forecasting

Gradient boosting on tabular features outperforms deep learning for this data volume (~8,760 hourly samples/year). LightGBM fits Lambda's 512 MB / 30s constraints. Quantile regression (α=0.10/0.90) provides calibrated prediction intervals.

**59 features** across 9 categories: calendar cycles, price lags (multi-day + 7d rolling stats), weather (temperature + solar radiation + wind), generation mix ratios, balancing price spreads, load forecasts, DE-LU cross-border prices, gas prices, holidays, solar position, and interaction terms.

**Optuna tuning**: 100 trials with 4-fold walk-forward cross-validation. Walk-forward (not random k-fold) prevents future data leakage in time-series. Huber loss for robustness to price spikes.

### Monitoring pipeline

CloudWatch Alarms detect Lambda errors or missing data → SNS topic → dedicated alarm_handler Lambda → Telegram message. This avoids polling and provides sub-minute alerting.

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI | Auto-docs, Pydantic validation, async-ready |
| Runtime | AWS Lambda (arm64 Docker) | Same image local and prod; arm64 for lower cold-start |
| ASGI adapter | Mangum | Lambda integration without modifying app code |
| Database | PostgreSQL on Supabase | Full SQL, free tier with no expiry |
| ML | LightGBM + Optuna | Tabular-optimized; fits Lambda memory/time constraints |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS | App Router + OGP metadata; Recharts for time-series |
| Hosting | Vercel | Free, auto-deploy on push |
| IaC | Terraform | Declarative, reproducible infrastructure |
| CI/CD | GitHub Actions | pytest → build → deploy → smoke test on every push |
| Monitoring | CloudWatch → SNS → Lambda → Telegram | Automated failure alerting |

## Infrastructure (Terraform-managed)

- **Lambda × 3**: API handler, scheduler, alarm handler
- **API Gateway v2** (HTTP API): routes to API Lambda
- **EventBridge**: 8 cron rules for data pipeline
- **ECR × 2**: API image + scheduler image
- **CloudWatch Alarms × 2**: error rate + missing data detection
- **SNS**: alarm fan-out topic
- **IAM**: least-privilege roles per Lambda

## CI/CD pipeline

```
git push main
  → pytest (214 tests, SQLite in-memory)
  → alembic migrate (Supabase)
  → Docker build --platform linux/arm64
  → ECR push (API + scheduler images)
  → Lambda function update
  → Smoke test (health endpoint)
```

## Cost

Runs entirely on permanent free tiers (no 12-month expiry): Lambda, API Gateway, EventBridge, CloudWatch/SNS, Vercel, Supabase. All external data APIs (ENTSO-E, SMHI, eSett, Riksbank) are free.

## ML performance

| Metric | Value |
|---|---|
| MAE improvement vs baseline | 58% (0.48 → 0.20 SEK/kWh) |
| Features | 61 (calendar, lags, weather, generation, balancing, load, DE-LU, gas, hydro reservoir, holidays, solar) |
| Training window | 365 days (full seasonal cycle) |
| Tuning | Optuna 100 trials, 4-fold walk-forward CV |
| Prediction intervals | Quantile regression (α=0.10/0.90) |

## Project structure

```
Unagi/
├── backend/
│   ├── unagi                           # CLI (./unagi help)
│   └── app/
│       ├── main.py                     # FastAPI + Mangum handler
│       ├── config.py                   # Pydantic settings
│       ├── routers/                    # 5 routers, 22 endpoints
│       ├── services/                   # 17 service modules
│       ├── db/                         # SQLAlchemy models + Alembic migrations
│       └── tasks/fetch_prices.py       # EventBridge scheduler handler
├── frontend/
│   └── src/
│       ├── components/                 # 11 components
│       ├── hooks/                      # 18 data hooks
│       └── utils/formatters.ts         # CET/CEST timezone helpers
├── infra/                              # Terraform (9 .tf files)
├── docs/                               # Documentation
├── Dockerfile                          # Multi-stage: dev / lambda / scheduler
├── docker-compose.yml                  # Local dev: FastAPI + PostgreSQL
└── .github/workflows/deploy.yml        # CI/CD pipeline
```
