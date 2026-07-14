# API Reference

## Public forecast feed (no key required)

Static JSON files served from the Cloudflare CDN at `https://catch.unagieel.net`. CORS-enabled, cacheable (15 min). Free for personal, non-commercial use with attribution — see [LICENSE.md](../LICENSE.md).

```
GET  /v1/index.json                        → area list + generation timestamp
GET  /v1/forecast/{SE1|SE2|SE3|SE4}.json   → today + 7 days ahead, hourly, per zone
GET  /v1/archive/{YYYY-MM-DD}/{AREA}.json  → frozen daily snapshot (immutable)
```

Each file covers today through d+7. Every day carries `kind`: settled days (`"actual"` — today, and tomorrow once Nord Pool publishes at ~13:00 CET) serve the real price in `value` with the model's prior prediction preserved in `forecast` (and its 80% interval in `low`/`high`), so forecast-vs-actual can be verified inside the file itself. Future days (`"forecast"`) serve the prediction in `value` (repeated in `forecast`). Select days by `date`/`kind`, never by array index. Settled hourly values are averages of the 15-minute settlement prices.

Also per file: unit (SEK/kWh, excl. VAT/fees), timezone, `cheapest_hours` per day (ranked by settled prices once a day settles), and a live `accuracy` block (28-day MAE incl. per-horizon breakdown, interval coverage). Within `/v1/`, fields are only ever added — breaking changes would go to `/v2/`. The feed refreshes after the nightly prediction run (~02:20 CET) and again when tomorrow's prices settle (~14:30 CET).

---

## Internal API

22 endpoints across 5 routers. All responses are JSON. Swagger UI available in development mode (`DEBUG=true`).

Authentication: `X-Unagi-Key` header required on all `/api/v1/*` endpoints.

---

## Prices

```
GET  /api/v1/prices/today                              → today's 15-min spot prices
GET  /api/v1/prices/tomorrow                           → tomorrow's prices (after 13:00 CET)
GET  /api/v1/prices/range?start=...&end=...            → date range prices (max 30 days)
GET  /api/v1/prices/history?days=90                    → daily min/avg/max summaries
GET  /api/v1/prices/multi-zone?days=90                 → all 4 zones (SE1–SE4) daily averages
GET  /api/v1/prices/cheapest-hours?duration=2          → cheapest consecutive window
```

## Forecast

```
GET  /api/v1/prices/forecast?model=lgbm               → ML forecast (LightGBM or same_weekday_avg)
GET  /api/v1/prices/forecast/accuracy?days=30          → per-model MAE/RMSE
GET  /api/v1/prices/forecast/accuracy/breakdown?by=hour → accuracy by hour or weekday
GET  /api/v1/prices/forecast/retrospective?date=...    → predictions vs actuals for past date
```

## Balancing & Exchange

```
GET  /api/v1/prices/balancing?date=...                 → imbalance prices (eSett EXP14)
GET  /api/v1/prices/exchange-rate                      → EUR/SEK from Riksbank (daily cache)
```

## Generation

```
GET  /api/v1/generation/today                          → today's generation mix (ENTSO-E A75)
GET  /api/v1/generation/date?date=...                  → historical generation data
```

## Simulation

```
POST /api/v1/simulate/consumption                      → fixed vs dynamic cost comparison
POST /api/v1/simulate/solar                            → PV generation + revenue estimate
```

## Notifications

```
GET    /api/v1/notify/vapid-public-key                 → VAPID key for browser push
POST   /api/v1/notify/subscribe                        → save push subscription
DELETE /api/v1/notify/subscribe                        → unsubscribe
```

## Health

```
GET  /health                                           → service liveness check
```
