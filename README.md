# Unagi — Swedish Electricity Price Forecast

> *Catch an E[el] for now and then.*

**[unagieel.net](https://unagieel.net)**

![Unagi dashboard](docs/unagi_top.png)

## What is this?

Unagi forecasts Swedish electricity spot prices up to 7 days ahead using machine learning, and shows you how accurate those forecasts actually are.

- **Hourly spot prices** for all four zones (SE1–SE4) with cheapest-window highlights
- **7-day ML forecast** — LightGBM trained on 365 days of price, weather, generation, and market data
- **Prediction accuracy on display** — MAE, prediction vs actual overlays, 80% confidence intervals with calibration tracking
- **Generation mix** — hydro, wind, nuclear, solar breakdown with carbon intensity
- **Cost simulators** — compare fixed vs dynamic contracts, estimate solar PV revenue
- **Light & dark themes** — marine blue by day, deep sea by night

No account required. No ads. Open source.

## How accurate is it?

Unagi publishes its forecast accuracy publicly — something [no other Swedish electricity tool does](https://unagieel.net).

| Model | MAE | vs Baseline |
|-------|-----|-------------|
| LightGBM (61 features, Huber loss) | **0.21 SEK/kWh** | 53% better than weekday average |
| Weekday Average (baseline) | 0.48 SEK/kWh | — |

The model is retrained daily on 365 days of data from ENTSO-E, SMHI, eSett, and Riksbank. Prediction intervals are calibrated using conformal quantile regression.

## Data sources

| Source | What | Update |
|--------|------|--------|
| [ENTSO-E](https://transparency.entsoe.eu/) | Day-ahead prices, generation mix | Hourly |
| [SMHI](https://www.smhi.se/) | Solar irradiance, temperature, wind | Hourly |
| [eSett](https://www.esett.com/) | Imbalance / balancing prices | 15-min |
| [Riksbank](https://www.riksbank.se/) | EUR/SEK exchange rate | Daily |

## Run locally

```bash
git clone git@github.com:mugime-shi/Unagi.git && cd Unagi
docker compose up                                  # API on :8100
cd frontend && npm install && npm run dev          # Next.js on :3000
```

Requires a `.env` file — see `.env.example` for required keys.

## Architecture

```
React 19 (Vercel) → API Gateway → Lambda (FastAPI) → PostgreSQL (Supabase)
                                       ↑
                    EventBridge crons: price fetch, ML predictions, notifications
                    CloudWatch → SNS → Telegram alerts
```

Full details: **[System Design](docs/SYSTEM_DESIGN.md)** · **[API Reference](docs/API.md)**

## Tech stack

Python 3.12 · FastAPI · LightGBM · Optuna · Next.js 16 · React 19 · TypeScript · Tailwind CSS · Recharts · AWS Lambda (arm64) · Terraform · GitHub Actions

## Contributing

Issues and PRs welcome. The ML model, feature engineering, and training pipeline are all in `backend/app/services/` and `backend/scripts/`.

## Author

**Shin** — Gothenburg, Sweden
