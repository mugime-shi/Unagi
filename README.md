# Unagi — Swedish Electricity Price Dashboard

> *Catch an E[el] for now and then.*

**[Live demo → unagieel.net](https://unagieel.net)** — zero-cost, fully automated

![Unagi dashboard](docs/unagi_top.png)

## Features

- **Spot prices** — 15-min ENTSO-E data with cheapest-window recommendations
- **ML forecast** — LightGBM next-day prediction with quantile regression
- **Energy analytics** — generation mix, renewable %, multi-zone (SE1–SE4)
- **Simulators** — fixed vs dynamic cost, solar PV revenue estimation
- **Notifications** — Telegram + browser push (VAPID)
- **Monitoring** — CloudWatch → SNS → Telegram failure alerting

## Tech stack

| | |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy · Mangum |
| **Frontend** | React 19 · Vite · Tailwind CSS · Recharts |
| **ML** | LightGBM · Optuna · quantile regression |
| **Infra** | AWS Lambda (arm64) · API Gateway · EventBridge · Terraform |
| **Data** | PostgreSQL (Supabase) · Alembic migrations |
| **CI/CD** | GitHub Actions → ECR → Lambda (auto-deploy on push) |

## Quick start

```bash
git clone git@github.com:mugime-shi/Unagi.git && cd Unagi
docker compose up                                  # API on :8100
cd frontend && npm install && npm run dev          # React on :5173
```

## Docs

- **[System Design](docs/SYSTEM_DESIGN.md)** — architecture, decisions, cost analysis, ML details
- **[API Reference](docs/API.md)** — endpoint documentation

## Contact

mugimeishi@gmail.com
