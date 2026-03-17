# ARCHITECTURE.md

# Namazu — Technical Architecture

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   React + Tailwind CSS                        │
│                      (Vercel)                                │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ Prices   │  │ History      │  │ Simulators         │     │
│  │ (Today/  │  │ (90d trend / │  │ (Cost comparison + │     │
│  │ Tomorrow/│  │  Zone comp.) │  │  Solar PV sim)     │     │
│  │ Review)  │  │              │  │                    │     │
│  └──────────┘  └──────────────┘  └────────────────────┘     │
└─────────────────────┬───────────────────────────────────────┘
                      │ REST API (JSON)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              API Gateway + Lambda (Docker image)             │
│              Python + FastAPI + Mangum (ASGI adapter)         │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ /prices  │  │ /simulate    │  │ /solar             │     │
│  └──────────┘  └──────────────┘  └────────────────────┘     │
│                                                              │
│  ┌──────────────────────────────────────────┐               │
│  │ EventBridge (daily 13:30 CET)            │               │
│  │ → fetch_prices Lambda (same Docker image) │               │
│  └──────────────────────────────────────────┘               │
└──────────┬──────────┬───────────────────┬───────────────────┘
           │          │                   │
           ▼          ▼                   ▼
┌──────────────┐ ┌──────────┐  ┌──────────────────┐
│ ENTSO-E API  │ │ SMHI API │  │ PostgreSQL       │
│ (Spot price) │ │ (Weather)│  │ (Supabase)       │
└──────────────┘ └──────────┘  └──────────────────┘

── Infrastructure: Terraform ───────────────
  Lambda, API Gateway, EventBridge, ECR, IAM

── Development ─────────────────────────────
  docker-compose up → FastAPI + PostgreSQL
  (同じDockerイメージがローカルでもLambdaでもECSでも動く)
```

---

## 2. Tech Stack — 選定理由

### Backend: Python + FastAPI

- **Why Python**: ターゲット企業（Tibber, Greenely）がPythonを多用。TRENDEのRuby/Railsとの明確な差別化。データ処理・ML拡張が自然
- **Why FastAPI**: 自動ドキュメント（Swagger UI）が面接デモで映える。型安全（Pydantic）。async対応でAPI呼び出しが効率的
- **Not Django**: フルスタックフレームワークは今回不要。APIに特化した軽量さがポートフォリオ向き
- **Lambda実行**: Mangum を使用。FastAPIをAWS Lambda上で実行するPython ASGIアダプター。`main.py` の末尾に `handler = Mangum(app)` を追加するだけで動作する

### Frontend: React + Tailwind CSS

- **Why React**: 業界標準。Tibber/Greenely のWebフロントエンドでも使用
- **Why Tailwind**: 素早くそれなりの見た目を作れる。デザイナー不在のソロプロジェクトに最適
- **Chart library**: Recharts（Reactとの統合が良い、時系列チャートに強い）

### Database: PostgreSQL (Supabase)

- **Why PostgreSQL**: 時系列データとリレーショナルデータの両方に対応
- **Why Supabase**: PostgreSQLのフルマネージドサービス（無料枠: 500MB）。期限なし。AWSのRDS free tierは12ヶ月限定のため、長期公開するポートフォリオにはSupabaseが適切
- **Not DynamoDB**: PostgreSQLの方がJOINやアグリゲーションが自然。価格比較クエリに向いている
- **本番想定**: RDS (db.t4g.micro) に移行可能。SQLとスキーマはそのまま使える

### Infrastructure — 3環境構成

**開発環境（Docker）**

- `docker-compose.yml` で FastAPI + PostgreSQL をローカルに構築
- `git clone → docker-compose up → localhost:8000` で即動作
- 実務でDocker + EC2を使っている経験と直結。面接官がcloneして手元で動かせる

**公開・デモ環境（AWS サーバーレス + Terraform）**

- API: Lambda（arm64 Dockerイメージ）+ API Gateway
  - MangumによりFastAPIをLambdaで実行。`handler = Mangum(app)` のみ追加
  - Dockerイメージは `public.ecr.aws/lambda/python:3.12` ベース、arm64アーキテクチャ
- スケジューラ: EventBridge → Lambda（毎日13:30 CETに価格取得、専用Dockerイメージ）
- イメージ管理: ECR（Elastic Container Registry）
- DB: Supabase PostgreSQL（Lambdaからの接続）
- Frontend: Vercel（React、free tier）
- IaC: **Terraform** で Lambda, API Gateway, EventBridge, ECR, IAM を管理
- コスト: 月0 SEK（全て無料枠内）

**本番スケール想定（README記載のみ）**

- 同じDockerイメージをECS/Fargateにデプロイ可能（Web Adapterの最大の利点）
- DB: RDS に移行（接続文字列の変更のみ）
- CDN: CloudFront をフロントエンドに追加
- Terraformの構成を拡張するだけで移行できることを言及
- 実務でECSを運用している経験があるため、面接では口頭で補足

### Why Mangum

```
Lambda Event → Mangum → FastAPI → Response → Mangum → Lambda Response

- Mangum は Python ASGI アプリを Lambda で動かすための薄いアダプター
- main.py に2行追加するだけ（try/except で ImportError を吸収し、ローカルでも動く）
- Lambda Web Adapter（awsguru ECR registry）は利用不可だったため Mangum を採用

ローカル:  docker-compose up → uvicorn が起動、Mangum は使われない
Lambda:    handler = Mangum(app) がエントリーポイントになる
```

### Why Terraform

- **宣言的**: インフラの「あるべき状態」をコードで定義
- **再現性**: `terraform apply` で同じ環境をいつでも再構築可能
- **ポートフォリオ価値**: IaC（Infrastructure as Code）の実践力を証明
- **実務との接続**: CloudFormation/SAMよりもマルチクラウド対応で市場価値が高い
- **構成**: `infra/` ディレクトリにモジュール化して配置

### Dockerfile（概要）

```dockerfile
# ── dev: ローカル docker-compose ────────────────
FROM python:3.12-slim AS base
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app

FROM base AS dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── lambda: AWS Lambda + Mangum (API関数) ───────
FROM public.ecr.aws/lambda/python:3.12 AS lambda
COPY backend/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ${LAMBDA_TASK_ROOT}/app
CMD ["app.main.handler"]   # Mangum handler

# ── scheduler: EventBridge トリガー ─────────────
FROM public.ecr.aws/lambda/python:3.12 AS scheduler
COPY backend/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ${LAMBDA_TASK_ROOT}/app
CMD ["app.tasks.fetch_prices.lambda_handler"]
```

- ローカル: `docker-compose up` → `dev` ターゲット、uvicorn で起動
- Lambda API: `lambda` ターゲット、Mangum がエントリーポイント
- Lambda Scheduler: `scheduler` ターゲット、EventBridge から直接呼び出し

---

## 3. External APIs

### 3.1 ENTSO-E Transparency Platform（電力スポット価格）

- **URL**: [https://transparency.entsoe.eu/](https://transparency.entsoe.eu/)
- **データ**: Day-ahead prices（翌日の15分/1時間単位スポット価格）
- **エリア**: SE3 (10Y1001A1001A482) — ヨーテボリを含むエリア
- **更新**: 毎日13:00 CET頃に翌日分が公開
- **認証**: 無料APIキー（登録制）
- **レート制限**: 400 requests/minute
- **形式**: XML（パース必要）
- **代替**: nordpoolgroup.com の非公式API、または[https://www.hvakosterstrommen.no/api](https://www.hvakosterstrommen.no/api) のラッパー

```python
# Example: ENTSO-E API call for SE3 day-ahead prices
import requests
from datetime import datetime, timedelta

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"
ENTSOE_TOKEN = "your-api-key"
SE3_AREA = "10Y1001A1001A482"

params = {
    "securityToken": ENTSOE_TOKEN,
    "documentType": "A44",           # Day-ahead prices
    "in_Domain": SE3_AREA,
    "out_Domain": SE3_AREA,
    "periodStart": "202603080000",   # YYYYMMDDHHMM
    "periodEnd": "202603090000",
}
response = requests.get(ENTSOE_BASE, params=params)
# Returns XML → parse with ElementTree
```

### 3.2 SMHI Open Data API（天候・日照データ）

- **URL**: [https://opendata-download-metobs.smhi.se/](https://opendata-download-metobs.smhi.se/)
- **データ**: 気温、全天日射量（1時間単位）
- **ステーション（2つ使用）**:
  - 日射量: Göteborg Sol (ID: 71415) — 日射量専用ステーション。パラメータ11のみここで取得可能
  - 気温: Göteborg A (ID: 71420) — 一般気象ステーション
- **更新**: リアルタイム（観測値）
- **認証**: 不要（完全オープン）
- **形式**: JSON（`date`フィールドはUTCのミリ秒epoch）
- **用途**: Layer 2の太陽光発電量シミュレーション

```python
# Example: SMHI global radiation data for Gothenburg
SMHI_BASE = "https://opendata-download-metobs.smhi.se/api"
PARAM_RADIATION = 11     # Global radiation (W/m²) — "Sol" stations only
PARAM_TEMPERATURE = 1    # Air temperature (°C)
STATION_SOL = 71415      # Göteborg Sol  (radiation)
STATION_A   = 71420      # Göteborg A    (temperature)

url = f"{SMHI_BASE}/version/1.0/parameter/{PARAM_RADIATION}/station/{STATION_SOL}/period/latest-months/data.json"
response = requests.get(url)
# response.json()["value"] → [{"date": <epoch_ms>, "value": "123.4", "quality": "G"}, ...]
```

### 3.3 eSett EXP14（Balancing / Imbalance prices）

- **ソース**: eSett Open Data API — Nordic Balance Settlement Institution
- **エンドポイント**: `GET https://api.opendata.esett.com/EXP14/Prices`
- **認証**: 不要（完全公開）
- **MBA コード**: SE3 = `10Y1001A1001A46L`（ENTSO-E EIC コードと同一）
- **パラメータ**: `mba`, `start`, `end`（UTC、`.000Z` ミリ秒必須）
- **データ**: SE3 のインバランス決済価格（15分単位、EUR/MWh）
  - **upRegPrice → A05 (Short)**: 上げ調整価格。BRP が不足した時に払う価格。急騰する
  - **downRegPrice → A04 (Long)**: 下げ調整価格。BRP が余剰時の精算価格。低い/負になる
  - **imblSalesPrice**: Nordic SIB 単一インバランス価格（2022年〜 = upReg or downReg の主方向）
- **データラグ**: ~5〜6時間（ENTSO-E A85 の ~12 時間より大幅改善）
- **カバレッジ**: 北欧4カ国（SE1-SE4 / FI / NO1-NO5 / DK1-DK2）

```python
# eSett EXP14 fetch pattern (esett_client.py):
import httpx
resp = httpx.get(
    "https://api.opendata.esett.com/EXP14/Prices",
    params={"mba": "10Y1001A1001A46L", "start": "2026-03-16T00:00:00.000Z", "end": "2026-03-17T00:00:00.000Z"}
)
for row in resp.json():
    if row["upRegPrice"] is not None:
        # → category A05 (Short), price in EUR/MWh
    if row["downRegPrice"] is not None:
        # → category A04 (Long), price in EUR/MWh
```

**データソース選定の経緯**

1. ENTSO-E A85 → 実装済み・動作確認済み。ただしデータラグ ~12h
2. SVK Mimer → 調査したが公開 API（全11エンドポイント）にインバランス決済価格なし。FCR/mFRR/aFRR 専用ポータル
3. **eSett EXP14 → 採用**。北欧4カ国の精算機関が直接管轄するデータ。ラグ ~5〜6h。認証不要

**なぜ IDA（Intraday）ではなく Balancing（eSett EXP14）か**

IDA（processType=A47）も調査（2026-03, 2025-12 の2期間、各288スロット）したが、ENTSO-E REST API は SE3 の XBID
連続取引価格を返さない。北欧はXBID連続市場のため、離散オークション清算価格として公開されていない。
eSett のバランシング価格は公開されており、需給ひっ迫を直接反映する価格スパイクが確認できる（実測: up to 639% vs DA）。

### 3.4 オプション: Open-Meteo（天気予報）

- **URL**: [https://api.open-meteo.com/](https://api.open-meteo.com/)
- **用途**: 翌日以降の日照予報 → 太陽光発電量の予測
- **認証**: 不要
- **メリット**: SMHIの観測値（過去）+ Open-Meteoの予報（未来）を組み合わせ可能

---

## 4. Data Model

### 4.1 spot_prices（スポット価格）

```sql
CREATE TABLE spot_prices (
    id            SERIAL PRIMARY KEY,
    area          VARCHAR(4) NOT NULL DEFAULT 'SE3',
    timestamp_utc TIMESTAMPTZ NOT NULL,
    price_eur_mwh DECIMAL(10,2) NOT NULL,    -- ENTSO-E raw price
    price_sek_kwh DECIMAL(10,4),             -- converted for display
    resolution    VARCHAR(10) DEFAULT 'PT15M', -- PT15M or PT60M
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(area, timestamp_utc, resolution)
);

CREATE INDEX idx_spot_prices_area_time ON spot_prices(area, timestamp_utc DESC);
```

### 4.2 balancing_prices（アンバランス価格 — eSett EXP14）

```sql
CREATE TABLE balancing_prices (
    id            SERIAL PRIMARY KEY,
    area          VARCHAR(4) NOT NULL DEFAULT 'SE3',
    timestamp_utc TIMESTAMPTZ NOT NULL,
    price_eur_mwh DECIMAL(10,2) NOT NULL,
    price_sek_kwh DECIMAL(10,4),
    category      VARCHAR(4) NOT NULL,   -- 'A04' (Long=供給超過) / 'A05' (Short=需要超過)
    resolution    VARCHAR(10) DEFAULT 'PT15M',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(area, timestamp_utc, category, resolution)
);

CREATE INDEX idx_balancing_prices_area_time ON balancing_prices(area, timestamp_utc DESC);
```

**spot_prices と別テーブルにした理由**

- 異なるマーケット、異なるデータソース（ENTSO-E A44 vs eSett EXP14）、異なるAPI形式
- `category`次元（Long/Short）が必要で、spot_pricesにはこの概念がない
- 清算タイミングが異なる（Day-ahead: 翌日13:00 / Balancing: 15分遅延連続）
- クエリパターンが異なる（DA: 日次参照 / Balancing: DA比較オーバーレイ）

### 4.3 weather_data（天候データ — Layer 2用）

```sql
CREATE TABLE weather_data (
    id              SERIAL PRIMARY KEY,
    station_id      INTEGER NOT NULL DEFAULT 71420,
    timestamp_utc   TIMESTAMPTZ NOT NULL,
    temperature_c   DECIMAL(5,1),
    global_radiation_wm2 DECIMAL(8,2),       -- W/m², 太陽光発電量計算に使用
    sunshine_hours  DECIMAL(4,1),
    source          VARCHAR(20) DEFAULT 'smhi',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(station_id, timestamp_utc, source)
);
```

### 4.3 generation_mix（発電ミックス — ENTSO-E A75）

```sql
CREATE TABLE generation_mix (
    id            SERIAL PRIMARY KEY,
    area          VARCHAR(4) NOT NULL DEFAULT 'SE3',
    timestamp_utc TIMESTAMPTZ NOT NULL,
    psr_type      VARCHAR(4) NOT NULL,       -- ENTSO-E PSR code: B12=水力, B14=原子力, B19=風力, etc.
    value_mw      DECIMAL(10,2) NOT NULL,    -- 発電量 (MW)
    resolution    VARCHAR(10) DEFAULT 'PT15M',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(area, timestamp_utc, psr_type)
);

CREATE INDEX idx_generation_mix_area_time ON generation_mix(area, timestamp_utc DESC);
```

### 4.4 weather_data（天候データ — Layer 2用）

```sql
CREATE TABLE weather_data (
    id              SERIAL PRIMARY KEY,
    station_id      INTEGER NOT NULL DEFAULT 71420,
    timestamp_utc   TIMESTAMPTZ NOT NULL,
    temperature_c   DECIMAL(5,1),
    global_radiation_wm2 DECIMAL(8,2),       -- W/m², 太陽光発電量計算に使用
    sunshine_hours  DECIMAL(4,1),
    source          VARCHAR(20) DEFAULT 'smhi',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(station_id, timestamp_utc, source)
);
```

### 4.5 forecast_accuracy（予測精度バックテスト）

```sql
CREATE TABLE forecast_accuracy (
    id                SERIAL PRIMARY KEY,
    target_date       DATE NOT NULL,           -- 予測対象日
    area              VARCHAR(4) NOT NULL DEFAULT 'SE3',
    model_name        VARCHAR(30) NOT NULL,    -- 'same_weekday_avg' or 'lgbm'
    hour              INTEGER NOT NULL,        -- 0-23 (ストックホルム時間)
    predicted_sek_kwh DECIMAL(10,4) NOT NULL,  -- 前日に記録される予測値
    actual_sek_kwh    DECIMAL(10,4),           -- 翌日に埋められる実績値 (nullable)
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(target_date, area, model_name, hour)
);

CREATE INDEX idx_forecast_accuracy_date_area ON forecast_accuracy(target_date, area);
```

**ワークフロー**:
1. Day N-1: cron ジョブが `record_predictions()` で明日の予測を24時間分保存
2. Day N: `fill_actuals()` が spot_prices から実績を `actual_sek_kwh` に埋める
3. `get_accuracy()` / `get_accuracy_breakdown()` で MAE/RMSE を集計

### 4.6 push_subscriptions（Web Push 通知購読）

```sql
CREATE TABLE push_subscriptions (
    id        SERIAL PRIMARY KEY,
    endpoint  TEXT NOT NULL,
    p256dh    TEXT NOT NULL,               -- ECDH public key (base64url)
    auth      TEXT NOT NULL,               -- Auth secret (base64url)
    area      VARCHAR(4) NOT NULL DEFAULT 'SE3',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(endpoint)
);
```

### 4.7 simulations（シミュレーション結果キャッシュ）

```sql
CREATE TABLE simulations (
    id                SERIAL PRIMARY KEY,
    simulation_type   VARCHAR(20) NOT NULL,   -- 'consumption' or 'solar'
    params_hash       VARCHAR(64) NOT NULL,   -- input parameters hash
    input_params      JSONB NOT NULL,
    result            JSONB NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. API Design

### Layer 1 Endpoints（消費最適化）

```
GET /api/v1/prices/today
  → 今日のSE3スポット価格（15分単位）
  Response: { area: "SE3", date: "2026-03-08", prices: [{time: "00:00", sek_kwh: 0.38}, ...] }

GET /api/v1/prices/tomorrow
  → 明日のスポット価格（13:00以降に取得可能）

GET /api/v1/prices/range?start=2026-03-01&end=2026-03-08
  → 期間指定の価格履歴（Review モードでも使用: 単日指定で過去日の15分スロット取得）

GET /api/v1/prices/cheapest-hours?date=2026-03-08&duration=2
  → 指定日の連続N時間で最安の時間帯
  Response: { cheapest_start: "02:00", avg_price_sek: 0.25, savings_vs_peak_pct: 62 }

GET /api/v1/prices/forecast?date=2026-03-18&area=SE3&model=lgbm
  → 翌日24時間の価格予測（model: same_weekday_avg | lgbm）
  Response: { slots: [{hour: 0, avg_sek_kwh: 0.32, low_sek_kwh: 0.25, high_sek_kwh: 0.40}, ...] }

GET /api/v1/prices/forecast/accuracy?area=SE3&days=30
  → モデル別の予測精度（MAE/RMSE）過去N日集計

GET /api/v1/prices/forecast/accuracy/breakdown?by=hour|weekday
  → 時間帯別 or 曜日別の予測精度内訳

GET /api/v1/prices/forecast/retrospective?date=2026-03-16&area=SE3
  → 指定過去日の予測値 vs 実績値（Review モードで使用）
  Response: { models: { lgbm: [{hour, predicted_sek_kwh, actual_sek_kwh}, ...], same_weekday_avg: [...] } }

POST /api/v1/simulate/consumption
  Body: { monthly_kwh: 500, contract_type: "fixed", fixed_price_sek: 1.20 }
  → 固定価格 vs ダイナミック価格の月額コスト比較
  Response: { fixed_cost: 600, dynamic_cost: 485, savings_sek: 115, savings_pct: 19 }
```

### Layer 2 Endpoints（売電最適化）

```
POST /api/v1/simulate/solar
  Body: {
    panel_kwp: 6.0,           -- パネル容量 (kWp)
    battery_kwh: 10.0,        -- 蓄電池容量 (kWh, 0 = なし)
    annual_consumption_kwh: 5000,
    month: "2026-07"
  }
  → 月間の売電収益 / 自家消費節約額 / 蓄電池最適化効果
  Response: {
    solar_generation_kwh: 720,
    self_consumed_kwh: 320,
    sold_to_grid_kwh: 400,
    revenue_sek: 180,
    savings_from_self_consumption_sek: 640,
    total_benefit_sek: 820,
    with_tax_credit: 1060,      -- 税控除あり（2025年まで）
    without_tax_credit: 820     -- 税控除なし（2026年以降）
  }

GET /api/v1/solar/roi
  Query: panel_kwp=6&battery_kwh=10&installation_cost_sek=120000
  → 投資回収シミュレーション（年単位）
```

---

## 6. Data Flow

### 6.1 価格データの取得・更新フロー

```
[EventBridge: 毎日 13:30 CET → fetch_prices Lambda (同じDockerイメージ)]
    │
    ▼
[ENTSO-E API] → 翌日のSE3 day-ahead prices (XML)
    │
    ▼
[Parser] → EUR/MWh → SEK/kWh 変換（Riksbank為替レート）
    │
    ▼
[PostgreSQL (Supabase): spot_prices テーブルへ UPSERT]
    │
    ▼
[次回のAPIリクエスト時に新データが返る]
```

### 6.2 太陽光発電シミュレーションフロー（Layer 2）

```
[User Input: パネル容量, 蓄電池容量, 月間消費量]
    │
    ▼
[SMHI API] → 指定月の日照データ取得（過去実績 or 予報）
    │
    ▼
[Solar Generation Model]
    │  PV output = panel_kwp × radiation × performance_ratio × hours
    │  (簡易モデル: performance_ratio ≈ 0.75〜0.85)
    │
    ▼
[Optimization Engine]
    │  各15分スロットで判断:
    │  - スポット価格が高い → 売電
    │  - スポット価格が低い → 蓄電（あれば）
    │  - 自家消費で相殺した方が得 → 自家消費
    │
    ▼
[Revenue Calculation]
    │  売電収益 = Σ(sold_kwh × spot_price)
    │  自家消費節約 = Σ(self_consumed_kwh × (spot_price + grid_fee + tax))
    │  蓄電池効果 = 安い時間に充電、高い時間に放電の差額
    │
    ▼
[Response → Frontend Dashboard]
```

---

## 7. Project Structure

```
Namazu/
├── README.md                    # English, portfolio-facing
├── PROJECT_BRIEF.md             # Japanese, design context
├── ARCHITECTURE.md              # This file
├── DOMAIN_KNOWLEDGE.md          # FIT vs Sweden market comparison
├── docker-compose.yml           # Dev: FastAPI + PostgreSQL
├── Dockerfile                   # Shared across dev / Lambda / ECS
│
├── backend/
│   ├── pyproject.toml           # Dependencies (FastAPI, httpx, uvicorn, etc.)
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point (no Lambda-specific code)
│   │   ├── config.py            # Settings, API keys, env-based switching
│   │   ├── models/
│   │   │   ├── spot_price.py    # Pydantic models
│   │   │   └── simulation.py
│   │   ├── routers/
│   │   │   ├── prices.py        # /api/v1/prices/*
│   │   │   ├── simulate.py      # /api/v1/simulate/*
│   │   │   └── solar.py         # /api/v1/solar/*
│   │   ├── services/
│   │   │   ├── entsoe_client.py # ENTSO-E API integration
│   │   │   ├── smhi_client.py   # SMHI weather data
│   │   │   ├── price_service.py # Price retrieval & caching
│   │   │   ├── optimizer.py     # Consumption optimization logic
│   │   │   └── solar_model.py   # PV generation & revenue calc
│   │   ├── db/
│   │   │   ├── database.py      # PostgreSQL connection (local & Supabase)
│   │   │   └── migrations/
│   │   └── tasks/
│   │       └── fetch_prices.py  # Price fetching (EventBridge trigger)
│   └── tests/
│       ├── test_prices.py
│       ├── test_optimizer.py
│       └── test_solar_model.py
│
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── PriceChart.jsx
│   │   │   ├── CheapestHours.jsx
│   │   │   ├── CostComparison.jsx
│   │   │   ├── SolarSimulator.jsx
│   │   │   └── RevenueChart.jsx
│   │   ├── hooks/
│   │   │   └── usePrices.js
│   │   └── utils/
│   │       └── formatters.js
│   └── public/
│
├── infra/                       # Terraform
│   ├── main.tf                  # Provider, backend config
│   ├── variables.tf             # Input variables
│   ├── outputs.tf               # API Gateway URL, etc.
│   ├── lambda.tf                # Lambda function (Docker image from ECR)
│   ├── api_gateway.tf           # API Gateway HTTP API
│   ├── eventbridge.tf           # Scheduled price fetching
│   ├── ecr.tf                   # Container registry
│   └── iam.tf                   # Lambda execution role & policies
│
└── .github/
    └── workflows/
        ├── ci.yml               # PR時: lint → test → build確認
        └── deploy.yml           # main push時: test → docker build → ECR push → terraform apply
```

### CI/CD: GitHub Actions

本プロジェクトで初めてGitHub Actionsを使用。現職ではCI/CDの経験はあるが、GitHub Actionsは新規習得。

**ci.yml（PRトリガー）**

```yaml
# PRが作られた時・更新された時に実行
on: pull_request
jobs:
  test:
    - pytest（バックエンドテスト）
    - docker build（イメージがビルドできることの確認）
```

**deploy.yml（mainブランチへのpushトリガー）**

```yaml
# mainにマージされた時に実行
on: push (branches: main)
jobs:
  deploy:
    - pytest
    - docker build & tag
    - ECR push（AWS credentials はGitHub Secrets）
    - terraform apply（infra/ ディレクトリ）
    - Vercel は自動デプロイ（GitHub連携）
```

---

## 8. Development Phases — Implementation Order

### Phase 1: Foundation（Week 1前半）

1. プロジェクト初期化（Python venv, FastAPI scaffold, React scaffold）
2. `docker-compose.yml` 作成（FastAPI + PostgreSQL、`docker-compose up` で即動作）
3. ENTSO-E API の疎通確認 → SE3のday-ahead prices取得成功
4. spot_prices テーブル作成（ローカルPostgreSQL）
5. `/api/v1/prices/today` endpoint 実装
6. フロントエンドで価格チャート表示（最小限のUI）

### Phase 2: Layer 1 MVP（Week 1後半〜Week 2前半）

1. `/api/v1/prices/tomorrow`, `/api/v1/prices/cheapest-hours` 実装
2. 「今安い/高い/普通」インジケーター
3. 消費シミュレーション（`/api/v1/simulate/consumption`）
4. 固定価格 vs ダイナミック価格の月額比較UI
5. 日次cron jobでの価格自動取得

### Phase 3: Layer 2 MVP（Week 2後半〜Week 3前半）

1. SMHI APIの疎通確認 → 日照データ取得
2. 太陽光発電量の簡易シミュレーションモデル
3. 売電収益計算ロジック（税控除あり/なし比較）
4. ソーラーシミュレーターUI
5. 月間収益ダッシュボード

### Phase 4: Polish & Deploy（Week 3後半）

1. レスポンシブデザイン調整
2. テスト追加
3. Terraform構成作成（`infra/`）: Lambda, API Gateway, EventBridge, ECR, IAM
4. Dockerfile最終調整（Lambda Web Adapter レイヤー追加）
5. GitHub Actions 構築（`ci.yml` + `deploy.yml`）
6. `git push → GitHub Actions → ECR push → terraform apply` でデプロイ
7. Supabase にDBマイグレーション
8. Vercel にフロントエンドデプロイ
9. README.md 作成（英語、ポートフォリオ向け）
10. GitHub リポジトリ公開

---

## 9. Key Technical Decisions

技術選定の根拠は上記各セクションに記載。面接向け Q&A は [INTERVIEW_PREP.md §4](INTERVIEW_PREP.md) に集約。

---

## 10. ML Price Prediction — LightGBM

### 10.1 なぜ LightGBM か

LightGBM（Light Gradient Boosting Machine）は Microsoft が開発した勾配ブースティング決定木（GBDT）ライブラリ。
電力価格予測に採用した理由:

- **表形式データに最強クラス**: 時間・曜日・季節・前日価格・発電ミックスといった構造化データに対して、深層学習より高精度かつ高速
- **欠損値をネイティブ処理**: generation_mix データがない時間帯でも `NaN` として自然に扱える。前処理不要
- **軽量・高速**: Lambda（512MB / 30s制約）上でも訓練+推論が完了する。PyTorch/TensorFlow は Lambda に載せにくい
- **解釈可能性**: `feature_importance()` で「どの特徴量が効いているか」を可視化できる → 面接で説明しやすい

### 10.2 LightGBM の仕組み（概要）

```
入力データ（特徴量行列）
    │
    ▼
┌─────────────────────────────────────────────┐
│  勾配ブースティング（Gradient Boosting）         │
│                                              │
│  1. 最初の予測 = データ全体の平均値               │
│  2. 残差（実際の値 − 予測値）を計算               │
│  3. 残差を予測する決定木を1本追加                 │
│  4. 学習率（0.05）で補正を加算                   │
│  5. 新しい残差を計算 → 2に戻る                   │
│  6. 500ラウンドまで繰り返し（early stoppingあり）  │
│                                              │
│  最終予測 = 平均値 + Σ(各木の補正 × 学習率)       │
└─────────────────────────────────────────────┘

LightGBM の特徴（vs XGBoost）:
- Leaf-wise 分割: 最も損失を減らすリーフを選んで分割（XGBoost は level-wise）
  → 同じ精度をより少ないラウンドで達成
- Histogram-based: 特徴量を離散ビンに変換してから分割点を探索
  → メモリ効率が高く、大規模データでも高速
- Categorical feature 対応: カテゴリ変数を one-hot 化せずに直接扱える
```

### 10.3 Namazu での実装

```
訓練データ                    予測
───────────────────────     ────────────────
[target_date − 90日]        [target_date]
     ↓                          ↓
  90日分の                    翌日24時間の
  (date, hour) 行             特徴量を構築
  = ~2,160行                  = 24行
     ↓                          ↓
  train/val 分割              model.predict()
  (最後7日 = val)                  ↓
     ↓                     24時間のSEK/kWh予測
  LightGBM 訓練
  (early stopping)
     ↓
  /tmp/ にキャッシュ
  (Lambda warm start)
```

**特徴量（19次元）**:

| カテゴリ | 特徴量 | 説明 |
|---------|--------|------|
| カレンダー | `hour`, `weekday`, `month` | 整数値 |
| カレンダー | `hour_sin/cos`, `weekday_sin/cos`, `month_sin/cos` | 周期性を表現する sin/cos エンコーディング。「23時→0時」の断崖を滑らかに |
| ラグ | `prev_day_same_hour` | 前日の同時間帯価格 |
| ラグ | `prev_week_same_hour` | 前週同曜日の同時間帯価格 |
| ラグ | `daily_avg_prev_day` | 前日の日平均価格 |
| 発電 | `gen_hydro/wind/nuclear_mw` | 前日の各電源の発電量（MW） |
| 発電 | `gen_total_mw` | 前日の総発電量 |
| 発電 | `hydro/wind/nuclear_ratio` | 各電源の構成比率 |

**ハイパーパラメータ**:

```python
{
    "objective": "regression",    # 回帰問題
    "metric": "mae",             # 平均絶対誤差で評価
    "num_leaves": 31,            # 木の複雑さ（デフォルト）
    "learning_rate": 0.05,       # 保守的な学習率
    "feature_fraction": 0.8,     # 各木で80%の特徴量をランダム使用
    "bagging_fraction": 0.8,     # 各木で80%のデータをランダム使用
    "bagging_freq": 5,           # 5ラウンドごとにバギング
    "verbose": -1,               # 出力抑制
}
# max 500 rounds, early stopping 20 rounds on validation set
```

**予測区間**: LightGBM は点推定のみ。low/high は訓練残差の ±1σ で簡易的に算出。
ベイジアンな不確実性推定（Quantile Regression や NGBoost）は将来の改善候補。

### 10.4 バックテスト基盤

```
forecast_accuracy テーブル
┌──────────────┬──────┬────────────────────┬──────┬──────────────────┬──────────────┐
│ target_date  │ area │ model_name         │ hour │ predicted_sek_kwh│ actual_sek_kwh│
├──────────────┼──────┼────────────────────┼──────┼──────────────────┼──────────────┤
│ 2026-03-17   │ SE3  │ same_weekday_avg   │ 0    │ 0.3200           │ 0.3150       │
│ 2026-03-17   │ SE3  │ lgbm               │ 0    │ 0.3180           │ 0.3150       │
│ ...          │      │                    │      │                  │              │
└──────────────┴──────┴────────────────────┴──────┴──────────────────┴──────────────┘

GET /api/v1/prices/forecast/accuracy?area=SE3&days=30
→ {
    "days": 30,
    "models": {
      "same_weekday_avg": { "mae_sek_kwh": 0.085, "rmse_sek_kwh": 0.12, "n_days": 28 },
      "lgbm":             { "mae_sek_kwh": 0.052, "rmse_sek_kwh": 0.07, "n_days": 28 }
    }
  }
```

面接向け LightGBM Q&A は [INTERVIEW_PREP.md §5](INTERVIEW_PREP.md) に集約。

---

## 11. Cost Estimate


| Resource          | Service                                 | Monthly Cost     |
| ----------------- | --------------------------------------- | ---------------- |
| Backend API       | Lambda free tier (1M requests/month)    | 0 SEK            |
| API routing       | API Gateway free tier (1M calls/month)  | 0 SEK            |
| Scheduler         | EventBridge (free for <14M invocations) | 0 SEK            |
| Frontend hosting  | Vercel free tier                        | 0 SEK            |
| Database          | Supabase free tier (500MB, no expiry)   | 0 SEK            |
| ENTSO-E API       | Free (registration required)            | 0 SEK            |
| SMHI API          | Free (open data)                        | 0 SEK            |
| Domain (optional) | Namazu.se or similar                  | ~100 SEK/year    |
| **Total**         |                                         | **~0 SEK/month** |


Note: AWS free tier for Lambda/API Gateway/EventBridge has no 12-month expiry — these are "always free" services within the usage limits.