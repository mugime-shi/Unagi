# TASKS.md
# Namazu — 実装タスクリスト

> Claude Codeでの作業単位として使う。各タスクは1セッションで完了できるサイズ。
> 完了したらチェックを入れる。

---

## Phase 1: Foundation（目安: Week 1前半）

### 1.1 プロジェクト初期化
- [x] Gitリポジトリ作成（`Namazu`）
- [x] `backend/` ディレクトリ: Python 3.12, requirements.txt, FastAPI scaffold
- [x] `frontend/` ディレクトリ: React (Vite), Tailwind CSS 初期設定
- [x] `docker-compose.yml`: FastAPI + PostgreSQL
- [x] `Dockerfile`: dev/lambda 2ターゲット構成（Lambda Web Adapter 対応）
- [x] `docker-compose up` で FastAPI が `localhost:8000` で応答することを確認
- [x] FastAPI の `/health` エンドポイントが動作すること

**完了条件**: `docker-compose up` → ブラウザで `localhost:8000/docs` にSwagger UIが表示される

### 1.2 ENTSO-E API 疎通
- [ ] ENTSO-E Transparency Platform でAPIキーを取得（要ユーザー登録）※ユーザー作業
- [x] `services/entsoe_client.py`: SE3のday-ahead prices を取得する関数
- [x] XMLレスポンスのパース（ElementTree）— PT15M / PT60M 両対応
- [x] EUR/MWh → SEK/kWh の変換（固定レート、config.pyで管理）
- [x] `scripts/fetch_prices_smoke.py`: APIキー設定後にコンソール出力で確認可能

**完了条件**: Pythonスクリプトを実行 → SE3の翌日24時間分のスポット価格がSEK/kWhで表示される

### 1.3 DB + 価格API
- [x] `db/database.py`: PostgreSQL接続（SQLAlchemy、docker-compose内のローカルDB）
- [x] `db/migrations/`: spot_prices テーブル作成（Alembic、ARCHITECTURE.md のスキーマ準拠）
- [x] `services/price_service.py`: ENTSO-Eから取得 → DBにUPSERT → DBから読み出し（APIキーなし時はモックデータにフォールバック）
- [x] `routers/prices.py`: `GET /api/v1/prices/today`, `GET /api/v1/prices/tomorrow` エンドポイント
- [x] テスト: `test_prices.py`（13テスト、SQLite in-memoryで動作）

**完了条件**: `curl localhost:8100/api/v1/prices/today` → SE3の今日のスポット価格（モック）がJSONで返る ✓
**Note**: docker-compose のポートを `API_PORT`（デフォルト8100）、`DB_PORT`（デフォルト5533）で設定可能に変更

### 1.4 最小フロントエンド
- [x] React アプリから `/api/v1/prices/today` を fetch（`usePrices` hook）
- [x] Recharts で時間帯別価格チャートを表示（`PriceChart.jsx`）
- [x] 現在の時間帯をハイライト（青い点）+ 安い/高い/普通インジケーター（`PriceIndicator.jsx`）
- [x] `npm run dev` で localhost:5173 → Vite proxy → API:8100 の構成で動作確認済み

**完了条件**: ブラウザで今日のSE3スポット価格の折れ線グラフが表示される ✓
**起動方法**: `docker compose up -d` → `cd frontend && npm run dev`

---

## Phase 2: Layer 1 MVP（目安: Week 1後半〜Week 2前半）

### 2.1 価格APIの拡充
- [x] `GET /api/v1/prices/tomorrow`（13:00以降に翌日分が取得可能）
- [x] `GET /api/v1/prices/range?start=...&end=...`（期間指定）
- [x] `GET /api/v1/prices/cheapest-hours?date=...&duration=2`（最安連続時間帯）
- [x] 明日の価格が未公開（13:00前）の場合のハンドリング（`published` フィールドで表現）

**完了条件**: 3つのエンドポイントが全て動作し、cheapest-hoursが正しい時間帯を返す ✓
**テスト**: 24テスト全通過（SQLite in-memory）

### 2.2 価格自動取得（Scheduler）
- [x] `tasks/fetch_prices.py`: 日次の価格取得スクリプト（CLIから実行可能）
- [x] 過去データのバックフィル機能（指定期間の価格をまとめて取得）
- [x] エラーハンドリング（API障害時のリトライ×3、ログ出力）
- [x] ローカルではcron or 手動実行、デプロイ時にEventBridgeに接続（`lambda_handler` 実装済み）

**完了条件**: `python -m app.tasks.fetch_prices --backfill 30` → 過去30日分の価格がDBに保存される ✓
**Note**: `backend/.env` の `DATABASE_URL` を `localhost:5533` に修正（ホストからの接続用）

### 2.3 消費シミュレーション
- [x] `POST /api/v1/simulate/consumption` エンドポイント
- [x] 入力: 月間消費量(kWh), 固定価格契約の価格, shiftable_pct, shift_hours
- [x] 出力: 固定価格コスト, ダイナミック平均コスト, 最適化時コスト, 節約額・節約率
- [x] 電力価格の構成要素を正確に反映（マージン, 送電料, エネルギー税, VAT）
- [x] テスト: `test_simulate.py`（14テスト全通過）

**完了条件**: 月500kWhの消費で固定 vs ダイナミックの比較結果が返り、数値が妥当 ✓

### 2.3b Göteborg Energi 月平均価格契約対応
- [x] 「月平均価格 × 使用電力量」契約タイプをシミュレーターに追加
  - 月の全スロット価格の平均値を契約価格として使用
  - 固定価格・月平均・ダイナミック・最適化の **4パターン比較**に拡張
- [x] フロントエンド: 4枚目のResultCard「Gbg Energi (mo. avg)」追加（`grid-cols-2 sm:grid-cols-4`）
- [x] 月平均の表示: 「This month's avg spot so far: X.XX SEK/kWh (N days)」を青文字で表示

**完了条件**: 自分のGöteborg Energi契約（月平均×kWh）でのコストが他契約と並んで表示される ✓
**Note**: 月平均価格はDBの当月データから計算。月途中はその時点までの平均を使用

### 2.4 Layer 1 フロントエンド完成
- [x] 今日・明日の価格チャート（タブ切り替え）
- [x] 「今安い / 高い / 普通」のカラーインジケーター（日平均比）
- [x] 「洗濯機（2h）/ 食洗機（2h）/ EV充電（4h）をいつ回すべきか」ウィジェット（`CheapHoursWidget.jsx`）
- [x] 消費シミュレーター: 月間kWhを入力 → 固定 vs ダイナミックの月額比較（`ConsumptionSimulator.jsx`）
- [x] レスポンシブ対応（flex-wrap・sm:px-6・グリッド対応）
- [x] 価格サマリーに月平均追加: Min / Avg (today) / Avg (month) / Max の4カード表示
  - `summary.month_avg_sek_kwh`（当月全スロット平均）をバックエンドで計算し返却
  - フロントエンド: `grid-cols-2 sm:grid-cols-4` でレスポンシブ4列

**完了条件**: 自分のスマホからアクセスして、今日の最安時間帯と消費シミュレーション結果が見える ✓
**起動方法**: `docker compose up -d` → `cd frontend && npm run dev`

---

## Phase 3: Layer 2 MVP（目安: Week 2後半〜Week 3前半）

### 3.1 天候データ取得
- [x] `services/smhi_client.py`: SMHI Open Data APIからヨーテボリの日照データ取得
- [x] 全天日射量（global radiation, W/m²）のパース（Parameter 11, Station 71415: Göteborg Sol）
- [x] 気温データ（Parameter 1）を同時取得、タイムスタンプで結合
- [x] `models/weather_data.py`: WeatherData ORM モデル
- [x] `migrations/b8f2c9d1a3e5_create_weather_data_table.py`: Alembicマイグレーション
- [x] weather_data テーブルへのUPSERT（PostgreSQL `ON CONFLICT DO UPDATE`）
- [x] テスト: `test_smhi.py`（10テスト全通過）

**完了条件**: ヨーテボリの直近数ヶ月の日射量データがDBに保存される ✓
**Note**: `fetch_and_store(db)` で全データ取得+保存。`alembic upgrade head` でテーブル作成

### 3.2 太陽光発電シミュレーション
- [x] `services/solar_model.py`: 発電量推定モデル
  - 計算式: `generation_kwh = panel_kwp × (radiation_wm2 / 1000) × performance_ratio`
  - 実SMHIデータ優先 → DBにデータなければ参照テーブルにフォールバック
  - 出力: 月間合計・日平均・時間単位スロット（SMHIデータ時のみ）
- [x] ヨーテボリの月別日射量の参照テーブル（DOMAIN_KNOWLEDGE.md参照）
- [x] テスト: `test_solar_model.py`（15テスト全通過）

**完了条件**: 6kWpパネルの7月の推定月間発電量が500〜800kWhの範囲に収まる ✓ (~773kWh)
**Note**: SMHIデータは時間単位。hourly_slotsにtimestamp+radiation+generationが入る

### 3.3 売電最適化ロジック
- [x] `POST /api/v1/simulate/solar` エンドポイント（`routers/solar.py`）
- [x] 入力: パネル容量, 蓄電池容量, 年間消費量, 対象月（YYYY-MM）, PR
- [x] 閾値ベース最適化: spot > daily_avg×1.2 → 売電優先、spot < daily_avg×0.8 → 充電/購入優先
- [x] 税控除あり（≤2025年）vs なし（2026年〜）の比較計算
  - eligible_kwh = min(sold_kwh, bought_kwh)（買電量上限の制約を反映）
  - 年間上限18,000 SEKも表示
- [x] テスト: `test_solar_model.py`（21テスト全通過）

**完了条件**: 税控除あり/なしで月次クレジット差が正しく計算される ✓
**Note**: savings = (total_cons - bought) × avg_full_retail（バッテリー放電分も含む正しい式）

### 3.4 Layer 2 フロントエンド
- [x] ソーラーシミュレーター入力フォーム（パネル容量, 蓄電池, 消費量, 対象月）
- [x] エネルギーバランス表示: 発電量 / 自家消費 / 売電 / 購入の4カード
- [x] 売電収益 / 自家消費節約額 / 蓄電池効果の内訳表示
- [x] 税控除廃止前後の比較ビュー（≤2025 vs 2026+）― 月次・年次の両方を表示
- [x] Layer 1 ↔ Layer 2 のナビゲーション（ヘッダー右上 Prices / Solar タブ）
- [x] データソースバッジ（SMHI real data / Reference table）
- [ ] 月間の発電量 vs 消費量チャート（Nice to have）

**完了条件**: ソーラーシミュレーターにパラメータを入力 → 税控除あり/なしの年間収益が表示される ✓
**実装ファイル**:
- `src/hooks/useSolar.js`: POST `/api/v1/simulate/solar`
- `src/components/SolarSimulator.jsx`: フォーム + 結果表示
- `src/App.jsx`: Prices / Solar レイヤーナビゲーション追加

---

## Phase 4: Deploy & Polish（目安: Week 3後半）

### 4.0 環境セットアップ（デプロイ前提条件）✓

#### AWS — 個人プロファイル追加 ✓
- [x] 個人AWSアカウントにログイン → IAMコンソールへ
- [x] IAMユーザー作成: `namazu`（AdministratorAccess）
- [x] `~/.aws/credentials` に `[personal]` プロファイルを追記
- [x] `~/.aws/config` に `[profile personal] region = eu-north-1` を追記
- [x] 動作確認: `aws sts get-caller-identity --profile personal`
- **Note**: 会社設定に `source_profile = default` が残っていたため除去。`AWS_REGION` 環境変数が会社設定でセットされているため、Terraform実行時は `AWS_REGION="" terraform ...` が必要

#### GitHub — 個人アカウントをSSHで接続 ✓
- [x] 個人用SSHキー生成: `~/.ssh/id_ed25519_personal`
- [x] `~/.ssh/config` に `Host github-personal` を追記（会社設定に影響なし）
- [x] GitHub個人アカウント (`mugime-shi`) に公開鍵を登録
- [x] GitHubに `Namazu` リポジトリ作成（private）
- [x] Initial commit → `git push -u origin main`
- [x] `~/.gitconfig` に `includeIf "gitdir:~/mugimeshi/"` を追記
- [x] `~/.gitconfig-personal` 作成（name: mugimeshi, email: mugimeishi@gmail.com）
- [x] `gh auth login` で `mugime-shi` アカウントを gh CLI に追加（PAT: repo + read:org + admin:org）
- [x] `megumishi`（会社）をデフォルトに設定、`mugime-shi` への切り替えは `.envrc` の `GH_TOKEN` で自動化

#### direnv ✓
- [x] `brew install direnv` + `~/.bash_profile` に `eval "$(direnv hook bash)"` を追記
- [x] `Namazu/.envrc` に `AWS_PROFILE=personal` + `GH_TOKEN=...` を設定
- [x] `direnv allow` 済み

**完了条件**: 達成 ✓

---

### 4.1 Terraform ✓（apply待ち）
- [x] `infra/main.tf`: provider（profile = personal、local state）
- [x] `infra/ecr.tf`: ECRリポジトリ × 2（namazu-api / namazu-scheduler）+ ライフサイクルポリシー
- [x] `infra/lambda.tf`: Lambda × 2（api: 512MB/30s, scheduler: 256MB/300s）
- [x] `infra/api_gateway.tf`: HTTP API + CORS + catch-allルート
- [x] `infra/eventbridge.tf`: 日次スケジュール cron(30 12 * * ? *)（12:30 UTC = 13:30 CET）
- [x] `infra/iam.tf`: Lambda実行ロール + CloudWatch Logs + ECR読み取りポリシー
- [x] `infra/variables.tf`, `infra/outputs.tf`, `infra/terraform.tfvars.example`
- [x] `Dockerfile` に `scheduler` ターゲット追加（`public.ecr.aws/lambda/python:3.12` ベース）
- [x] `terraform init` + `terraform validate` 成功
- [x] `terraform plan`: 18 to add, 0 to change, 0 to destroy ✓
- [x] ECR only apply → Docker build（arm64）→ push → full apply 完了
- [x] `curl https://5ouka6u81a.execute-api.eu-north-1.amazonaws.com/api/v1/prices/today` → 実データ返却 ✓

**完了条件**: 達成 ✓
**API Gateway URL**: `https://5ouka6u81a.execute-api.eu-north-1.amazonaws.com`
**Note**:
- Lambda Web Adapter（`awsguru` ECRレジストリ）が存在しなかったため Mangum に変更
- Dockerイメージは `linux/arm64` でビルド（Lambda architecture = arm64）
- `terraform apply` 時は `AWS_REGION=eu-north-1` の明示指定が必要（会社の `AWS_REGION` 環境変数が干渉するため）

### 4.2 Supabase 接続 ✓
- [x] Supabase プロジェクト作成（free tier、West EU / Ireland、eu-west-1）
- [x] スキーママイグレーション実行（`spot_prices` + `weather_data` テーブル作成）
- [x] Lambda の環境変数に Supabase 接続文字列を設定（terraform.tfvars経由）
- [x] `alembic upgrade head` 成功（Session Pooler経由：IPv4対応）

**完了条件**: 達成 ✓
**Note**:
- Direct connection（`db.xxx.supabase.co`）は IPv6 のみ対応のため、このネットワーク（IPv4）からは接続不可
- Session Pooler（`aws-1-eu-west-1.pooler.supabase.com:5432`）を使用
- Alembic env.py を `config.set_main_option` 方式から `create_engine` 直接呼び出しに変更（`configparser` の `%` 解釈エラー回避）
- Supabase DBパスワード: 記号なし（URLエンコード不要）に変更済み

### 4.3 GitHub Actions ✓
- [x] `.github/workflows/deploy.yml`: main push時に pytest → **alembic migrate** → ECR push → Lambda update → smoke test
- [x] GitHub Secrets 設定: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DATABASE_URL`, `ENTSOE_API_KEY`
- [x] push → Actions成功（2m27s）→ `/health` 200 確認
- [x] **Migration自動化**: `deploy.yml` に `cd backend && alembic upgrade head` ステップを追加（step 2）
  - テスト後・ECR push 前に実行 → 新Lambdaが起動した時点でスキーマが確定している
  - alembic はべき等（同じ migration を2回適用しても安全）

**完了条件**: 達成 ✓
**Note**:
- CI/CDを1ファイルに統合（ソロ開発のため）。コメントにチーム開発での分割方針を記載
- YAML構文: ステップ名に `:` を含む場合はクォート必須
- `docker/build-push-action` は `provenance: false` 必須（デフォルトのOCI image indexはLambda非対応）
- arm64クロスビルドには `docker/setup-qemu-action` + `docker/setup-buildx-action` が必要
- **ローカル migration**: `Dockerfile dev` ターゲットが起動時に `alembic upgrade head` を自動実行（`alembic.ini` をコンテナにコピー済み）。`docker compose up` するだけでローカル DB も常に最新スキーマになる

### 4.4 Vercel デプロイ ✓
- [x] Vercel にフロントエンドをデプロイ（`namazu-el.vercel.app`）
- [x] GitHubリポジトリ（`mugime-shi/Namazu`）と Vercel プロジェクトを接続
- [x] `frontend/vercel.json`: `/api/*` → Lambda への rewrite proxy + SPA フォールバック
- [x] CORS設定: `main.py` に `https://namazu-el.vercel.app` を追加
- [ ] カスタムドメイン設定（任意）

**完了条件**: 達成 ✓ — `https://namazu-el.vercel.app` でリアルデータが表示される
**Note**:
- Vercel の Root Directory を `frontend` に設定必須（`frontend/vercel.json` を認識させるため）
- `vercel.json` には `buildCommand` と `outputDirectory` の明示が必要（自動検出が不安定だったため）
- Vercel GitHub App に `Namazu` リポジトリへのアクセス権を付与してから接続

### 4.5 README & ドキュメント ✓
- [x] `README.md`（英語）: プロジェクト概要、デモURL、ローカルセットアップ手順、アーキテクチャ図、テックスタック、APIエンドポイント一覧、コスト表
- [ ] Swagger UI（`/docs`）が公開URLでアクセス可能であること ※ 現状 `/docs` は Lambda からも到達可能
- [ ] コードにdocstringとコメント（英語）

**完了条件**: READMEを読んだ面接官が、5分以内にプロジェクトの価値を理解できる

---

## Phase 5: Nice to have（時間があれば）

### 5.1 蓄電池最適化 ✓
- [x] 簡易的な充放電スケジューリングアルゴリズム（閾値ベース: HIGH×1.20 / LOW×0.80）
- [x] 蓄電池あり/なしの収益比較（baseline フィールドをAPIに追加、フロントで並列カード表示）

### 5.2 履歴データ分析 ✓
- [x] 過去90日の価格トレンドチャート（GET /api/v1/prices/history, Recharts AreaChart）
- [x] 期間min/avg/maxサマリーカード、破線で期間平均を表示

### 5.3 日本のFIT比較ビュー — スキップ
- 評価: ターゲット企業（Tibber, Greenely）はスウェーデン市場のプロ。FIT比較は技術的深度もドメイン深度も示せない。「なぜスウェーデンで働きたいか」は面接の口頭で語る話。5.5に時間を使う方がROI高い。

### 5.4 多言語対応
- [ ] 英語 / 日本語 / スウェーデン語

### 5.5 面接準備 ✓
- [x] 英語での5分間プレゼン原稿作成（INTERVIEW_PREP.md §1）
- [x] 想定質問と回答の練習（INTERVIEW_PREP.md §2 — 技術/ドメイン/モチベーション）
- [x] ライブデモのシナリオ作成（INTERVIEW_PREP.md §3 — 8ステップ + 当日チェックリスト）

---

## Phase 6: Polish & Differentiation（All S を目指す）

### 6.1 CET/CEST 夏時間対応 ✓
- [x] バックエンド全箇所の `UTC+1` 固定を `ZoneInfo("Europe/Stockholm")` に置き換え
  - 対象: `prices.py` の CET 日付グルーピング、`solar_model.py` の `_get_hourly_spot`、`history` エンドポイント
- [x] 夏時間境界をまたぐテストケースを追加
- **なぜ**: 年間6ヶ月（3月末〜10月末）で価格が1時間ズレる。エネルギー企業面接官は必ず気づく

### 6.2 価格ゾーン切り替え（SE1-SE4）✓
- [x] バックエンド: `GET /api/v1/prices/today?area=SE1` など既存の area パラメータを全エンドポイントで公開
  - `prices.py` のエンドポイントに `area: str = Query("SE3", ...)` を追加
  - `history`, `range`, `cheapest-hours` も対応
- [x] フロントエンド: ヘッダーにエリアセレクター（SE1/SE2/SE3/SE4）を追加
  - 選択したエリアを全 API リクエストに渡す
  - ヘッダーの `SE3 · Göteborg` をエリアに応じて動的に変更
- **なぜ**: バックエンドは準備済みなのにUIがSE3固定は機会損失。スウェーデン全土対応になる

### 6.3 マルチゾーン比較チャート ✓
- [x] `GET /api/v1/prices/multi-zone?days=N` 新エンドポイント（SE1-SE4 の日次平均を一括返却）
- [x] History ページに「Zone Comparison」タブを追加
  - 4ゾーンの日次平均を同一チャートに重ねる（Recharts LineChart、4色）
  - ゾーン間の価格差（送電ボトルネック）を可視化
  - データなし時はバックフィルコマンドを UI に表示
- [x] `fetch_prices.py` Lambda handler を全4エリア毎日取得に更新
- [x] テスト追加（83テスト全通過）
- **バックフィル必須**: SE1/SE2/SE4 のデータが DB にない場合、下記コマンドで初回投入が必要
  ```bash
  # Lambda 経由（一回実行）:
  aws lambda invoke --function-name namazu-scheduler \
    --payload '{"backfill_days":90}' /dev/null --profile personal

  # またはローカル（DATABASE_URL=Supabase で各エリア実行）:
  python -m app.tasks.fetch_prices --backfill 90 --area SE1
  python -m app.tasks.fetch_prices --backfill 90 --area SE2
  python -m app.tasks.fetch_prices --backfill 90 --area SE4
  ```
- **なぜ**: 北欧電力市場の構造（北部安 / 南部高）をビジュアルで証明できる。面接での差別化

### 6.4 明日の価格通知 ✓（PWA Web Push + Telegram Bot）
- [x] **PWA Web Push**（ブラウザ通知）
  - `frontend/public/sw.js`: Service Worker（プッシュ通知受信・表示）
  - `frontend/public/manifest.json`: PWAマニフェスト（ホーム画面追加対応）
  - `frontend/src/hooks/usePushNotification.js`: VAPID購読 / 権限取得 / subscribe / unsubscribe
  - `frontend/src/components/NotificationBell.jsx`: ヘッダーのベルアイコン（青=購読中）
  - `backend/app/models/push_subscription.py`: push_subscriptions テーブル（ORM）
  - `backend/app/db/migrations/versions/c9d1e2f3a4b5_...`: Alembic migration
  - `backend/app/services/notify_service.py`: Web Push 送信（pywebpush）
  - `backend/app/routers/notify.py`: `GET /vapid-public-key`, `POST/DELETE /subscribe`, `POST /test`
  - `backend/scripts/gen_vapid_keys.py`: VAPID鍵生成スクリプト（一回だけ実行）
  - VAPID keys 生成済み、ローカルDB migration 適用済み
- [x] **Telegram Bot**（メイン通知チャネル）
  - `backend/app/services/telegram_service.py`: MarkdownV2 整形メッセージ送信（httpx）
    - 翌日の avg / min / max + 最安2h枠 + 最高値2h枠 を通知
  - EventBridge 13:30 CET → `fetch_prices.py` → `send_telegram_alert()` の自動呼び出し
  - `POST /api/v1/notify/telegram-test`: ローカルテスト用エンドポイント
  - Bot: `@Namazu_notify_bot`（設定済み）
- [x] テスト: `tests/test_notify.py`（12テスト、100テスト全通過）
- **なぜ**: 「毎日使う」を本当に実現。PWAは技術デモ、Telegramが実用チャネル
- **本番デプロイ時の追加作業**:
  - GitHub Actions Secrets に `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` を追加
  - Terraform `terraform.tfvars` 経由で Lambda 環境変数に追加
  - Supabase に `alembic upgrade head` を実行（push_subscriptions テーブル作成）

### 6.5 簡易価格予測 ✓
- [x] `GET /api/v1/prices/forecast?date=YYYY-MM-DD&area=SE3&weeks=8` エンドポイント
  - 過去 N 週の同曜日・同時間帯の平均で翌日レンジを予測（p10/p50/p90）
  - `build_forecast()` in `price_service.py`: 同曜日 rows をフィルタ → 時間別 avg/low/high 計算
- [x] フロントエンド: tomorrow タブに予測バンド（薄色 indigo の range area）を表示
  - `PriceChart.jsx`: LineChart → ComposedChart に変更、stacked Area で帯域表示
  - `useForecast.js` hook + `App.jsx` で tomorrow 選択時に自動取得
  - ツールチップに予測レンジ（forecast 0.xx–0.xx）を表示
- [x] テスト追加（88テスト全通過）
- **なぜ**: ML/データサイエンス的思考を示す。Tibber/Greenely のコア事業に直結

---

---

## Phase 7: Post-Launch Quality Improvements（EVALUATION.md の改善ロードマップに基づく）

### 7.1 Priority 1 — 面接対策（工数: 小）✓
- [x] P1-1: コード内コメント追加（`solar_model.py` dispatcher/savings/skattereduktion, `notify_service.py` VAPID claims）
- [x] P1-2: `/notify/test` + `/notify/telegram-test` を `DEBUG=true` 時のみ有効（本番は404）
- [x] P1-3: ローディングスケルトン（チャート枠 + 4枚カードのanimate-pulseシルエット）

### 7.2 Priority 2 — インフラ成熟度（工数: 中）✓
- [x] P2-1: `infra/monitoring.tf` — CloudWatch Alarm → SNS → alarm_handler Lambda → Telegram
  - scheduler: エラー1件で即通知（5分窓、閾値0）
  - api: 15分持続エラーで通知（3×5分窓、閾値5）
  - `backend/alarm_handler.py`: stdlib onlyのPython handler（zipデプロイ、Dockerイメージ不要）
- [x] P2-2: `infra/api_gateway.tf` — HTTP API v2 stage throttling（100 req/s, burst 200）
- [x] P2-3: `infra/main.tf` — S3 + DynamoDB remote backendをコメントブロックで文書化（bootstrap手順付き）

**適用方法**: `AWS_REGION=eu-north-1 terraform apply` で monitoring.tf の全リソースが作成される
**注意**: `terraform init` が必要（archive providerが新規追加されたため）

### 7.3 Priority 3 — テスト深化（工数: 中）✓
- [x] P3-1: ENTSO-E / SMHI クライアントの httpx mock テスト（+8テスト）
  - entsoe: network error / HTTP 401 / date window外のXML / unknown resolution / 複数TimeSeries
  - smhi: `_fetch_parameter` HTTP成功 / HTTPStatusError / network error
- [x] P3-2: DST遷移日をまたぐ価格グルーピング integration テスト（+4テスト）
  - spring-forward 2025-03-30: 23h day — 01:00 UTC → 03:00 CEST（存在しない02:00 CETをスキップ）
  - fall-back 2025-10-26: 25h day — 01:00 UTC → 02:00 CET（繰り返す時間帯）
  - history endpoint でそれぞれ23スロット / 25スロットを検証

**完了条件**: 達成 ✓ — `pytest tests/` → 112テスト全通過（100→112）

---

## Phase 8: マルチマーケット表示 — Day-ahead + Intraday + Balancing

### なぜやるか（EVALU_2.txt の外部評価を踏まえて）

採用マネージャー視点の評価で「リアルタイム性がない」が最大の弱点として指摘された。
現在の Namazu は Day-ahead（前日オークション結果）のみを表示しており、
**「今」の市場で何が起きているかが見えない**。

電力市場は3層構造:
1. **Day-ahead（日前市場）** — 前日 ~13:00 CET にオークションで確定。翌日の24時間分。変わらない。
2. **Intraday（当日市場 / IDA）** — 前日 ~15:00 CET 以降、1日3回のオークション（IDA1/IDA2/IDA3）で修正価格が出る。「予想の修正」。
3. **Balancing（バランシング市場）** — TSO（Svenska Kraftnät）がリアルタイムで需給調整。事後的に価格公表。「グリッドのストレス度」。

3つを重ねることで「前日の予想 → 当日の修正 → リアルタイムの結果」が1画面でわかる。
**個人開発でここまで電力市場を可視化しているプロジェクトは極めて稀。**

面接で語れること:
> 「Day-ahead は前日のオークション結果です。でもそれだけでは "昨日の予想" しか見えません。
> IDA のオークション結果を重ねることで、配送直前に市場参加者がどう修正したかが見えます。
> さらに SVK のバランシングデータで、TSO がリアルタイムにどれだけ調整介入したかまで可視化しています。」

### 8.1 P8-1: Intraday（IDA）重ね表示（工数: 小〜中）

**データソース**: ENTSO-E Transparency Platform（既存と同じ API キー）
**技術的変更点**: `documentType=A44` に `processType=A47` を追加するだけ。
同じ XML 構造 → 既存の `_parse_xml` がそのまま動く。

- [ ] ENTSO-E API 疎通確認（processType=A47 で SE3 の IDA データ取得）
- [ ] `spot_prices` テーブルに `market_type` カラム追加（'day_ahead' / 'intraday'）
  - 既存データは全て 'day_ahead' にマイグレーション
- [ ] `entsoe_client.py` に `fetch_intraday_prices()` 追加
- [ ] Scheduler Lambda に IDA 取得を追加（Day-ahead 取得後に実行）
- [ ] API エンドポイント更新: `/prices/today` レスポンスに intraday 価格を含める
- [ ] フロントエンド: PriceChart に Intraday ライン追加（Day-ahead と色分け）
- [ ] テスト追加

**IDA スケジュール（取得タイミング）**:
- IDA1: ~15:00 CET（前日）— 翌日全時間帯の修正価格
- IDA2: ~22:00 CET（前日）— 残り時間帯
- IDA3: ~10:00 CET（当日）— 午後〜夜の最終修正

**DB 負荷**: 24行/日の追加。年間 ~1MB。Supabase 500MB 枠に余裕あり。

### 8.2 P8-2: Balancing 指標表示（工数: 中）✓

**データソース**: eSett Open Data API（EXP14/Prices）
**調査結果**: SVK Mimer は公開 API にインバランス決済価格エンドポイントを持たない（全クエリが空配列を返す）。
eSett（Nordic Balance Settlement）が公式かつ最良のソース：認証不要・REST・15分単位・約5〜6時間遅延。

- [x] SVK Mimer API 調査 → インバランス価格エンドポイントなし（全11エンドポイント確認）
- [x] eSett Open Data API 調査（`https://api.opendata.esett.com/openapi?format=json` で全仕様取得）
  - EXP14/Prices: `upRegPrice`（上げ調整 = A05 Short）/ `downRegPrice`（下げ調整 = A04 Long）
  - MBA コード: SE3 = `10Y1001A1001A46L`
- [x] `esett_client.py` 新規作成（ENTSO-E A85 を完全置き換え）
  - 認証不要、データラグ ~5〜6h（ENTSO-E A85 の ~12h より大幅改善）
  - upRegPrice → category "A05"、downRegPrice → category "A04" にマップ
- [x] 既存 `balancing_prices` テーブルをそのまま流用（DBスキーマ変更なし）
- [x] `balancing_service.py`: import を `esett_client` に変更、`api_key` 引数削除
- [x] `routers/prices.py`: source フィールドを "eSett EXP14" に更新
- [x] フロントエンド: `PriceChart.jsx` の imb_short / imb_long オーバーレイ（変更なし）
- [x] `useBalancing.js`: 今日のデータ → fallback to 昨日（変更なし）

**eSett EXP14 フィールド詳細**:
```
upRegPrice   (A05 Short) = 上げ調整価格。BRPがショート（不足）時に払う罰金価格。スパイクする
downRegPrice (A04 Long)  = 下げ調整価格。BRPがロング（余剰）時の精算価格。安い/負にもなる
imblSalesPrice           = Nordic SIB（2022年〜）の単一インバランス価格 = upRegPrice が主方向時
```

**なぜSVK Mimerではなく eSett か**:
- Mimer は FCR/mFRR/aFRR の予備力データポータル。インバランス決済価格 (reglerpris) は公開 API にない
- eSett は北欧4カ国（SE/FI/NO/DK）の共同精算機関。インバランス決済を直接管轄
- データ鮮度: eSett ~5〜6h lag vs ENTSO-E A85 ~12h lag

### 8.3 P8-3: ARCHITECTURE.md 更新（工数: 小）✓

- [x] ARCHITECTURE.md §3.3 を eSett EXP14 に更新
- [x] ARCHITECTURE.md §4.2 のコメント更新
- [x] DOMAIN_KNOWLEDGE.md §2.2-A の Balancing データソースを eSett に更新
- [x] DOMAIN_KNOWLEDGE.md の面接 Q&A を eSett 対応に更新

### 完了条件 ✓
- [x] Day-ahead + Balancing (eSett EXP14) の2本ラインがチャートに表示される
- [x] 今日のインバランス価格が ~5〜6h lag で取得可能（ENTSO-E A85 より改善）
- [x] ARCHITECTURE.md / DOMAIN_KNOWLEDGE.md が更新されている

---

## Phase 9: 発電ミックス表示（再エネ比率）

**目的**: ENTSO-E A75（発電種別実績）を取得し「今の電力の再エネ比率」を可視化。
価格だけでなく "グリーン度" も提供することで差別化ポイントを追加する。

**データソース**: ENTSO-E Transparency Platform（既存 API キー流用）
- Document Type A75: Actual Generation Per Production Type
- ~15-30分遅延。風力・太陽光・水力・原子力などの種別ごとの実発電量

### 9.1 P9-1: ENTSO-E A75 疎通確認（工数: 小）✓

- [x] ENTSO-E A75 で SE3 の発電ミックスが取得できるか確認
  - SE3 で取得できる psr_type: B04(Gas), B12(Hydro), B14(Nuclear), B16(Solar), B19(Wind), B20(Other)
  - B12(Hydro ~1500MW) が主力。北部風力は SE3 には少ない
- [x] `entsoe_client.py` に `fetch_generation_mix()` 追加
  - NS_GEN 名前空間、ステップ関数エンコーディングを展開して完全な15分スロットに変換
  - PSR_GROUP マッピング、RENEWABLE_PSR セット定義
- [x] DB: `generation_mix` テーブル新規作成（Alembic migration: e2f3a4b5c6d7）
  - UNIQUE(area, timestamp_utc, psr_type)、UPSERT対応

### 9.2 P9-2: バックエンド実装（工数: 中）✓

- [x] `generation_service.py` 新規作成
  - upsert_generation / get_generation_for_date / build_generation_summary
  - renewable_pct (hydro+wind+solar)、carbon_free_pct (+nuclear)
  - 時間別 time_series（将来のチャート用）
- [x] `routers/generation.py`: `GET /api/v1/generation/today` + `/date`
  - 今日データなし → live fetch → fallback to yesterday
- [x] `main.py` にルーター追加

### 9.3 P9-3: フロントエンド表示（工数: 中）✓

- [x] `useGeneration.js` hook 追加
- [x] 再エネ・カーボンフリー・Hydro/Wind/Nuclear バッジを PriceIndicator 下に表示
- [x] バッジ上に「Generation mix · as of HH:MM CET/CEST（実際のラグ時間）」を表示
  - CET/CEST を Intl API で動的取得（夏時間対応）
  - ラグ時間も実測値を動的表示（固定 "~15 min lag" ではなく実際の分/時間）
- [ ] 発電ミックス積み上げグラフ（stacked area chart）→ Phase 10.1 として正式タスク化

### 9.4 P9-4: バグ修正（工数: 小）✓

- [x] **EIC コードバグ修正**: `generation_service.py` が "SE3" をそのまま ENTSO-E `in_Domain` に渡していた
  - 修正: `_AREA_TO_EIC.get(area, area)` で EIC コード（"10Y1001A1001A46L"）に変換
- [x] **データ鮮度バグ修正**: DB にデータが1行でもあると永久にキャッシュされる問題
  - 修正: `latest_slot` の age が 20分超なら ENTSO-E に再 fetch（generation）
  - 修正: `latest_slot` の age が 30分超かつ today なら eSett に再 fetch（balancing）
- [x] **UTC タイムゾーンバグ修正**: DB から返る naive datetime を JS が localtime として解釈し1時間ずれる
  - 修正: `build_generation_summary()` で naive datetime に `+00:00` を付与してから JSON に出力

**完了条件** ✓
- [x] 今日の再エネ比率（%）が UI に表示される
- [x] データは ENTSO-E A75 から最新スロットを取得（ページアクセス時に 20分超なら自動再 fetch）
- [x] タイムスタンプが Stockholm 時刻で正確に表示される

**実装メモ**:
- SE3 は水力（B12 ~1500MW）が圧倒的主力。Renewable % は高め
- 北部風力(SE1/SE2)からの輸入分は A75 に含まれない → SE3 表示値は実消費グリーン度より低い可能性
- ENTSO-E A75 のラグは ~15-30分と文書化されているが、実測では 1-2時間になることがある（SE3 固有の遅延？）
- Lambda スケジューラーへの A75 組み込みは未実施（オンデマンドフェッチで充足）

---

## Phase 10: フロントエンド仕上げ（フロントエンド A → S）

### 10.1 Generation Mix Stacked Area Chart（工数: 小）

**前提**: バックエンドは `time_series`（毎時バケット: hydro/wind/nuclear/other MW）を既に返している。フロントエンドのみの変更で完結。

- [x] `GenerationChart.jsx` 新規作成
  - Recharts `AreaChart` + `stackOffset="none"`（面グラフ、各電源を積み上げ）
  - X 軸: Stockholm 時刻（00:00〜現在）、Y 軸: MW
  - 電源カラー: Hydro=青、Wind=シアン、Nuclear=黄、Solar=橙、Other=グレー
- [x] 既存バッジ行の下に配置（バッジはサマリーとして残す）
- [x] 価格チャートと上下に並べて「発電ミックス → 価格」の因果が視覚的に見えるレイアウト
- [x] データなし / ローディング時のスケルトン UI（time_series が空なら null を返す）

**完了条件**: 今日の 00:00〜現在の発電ミックスが積み上げ面グラフで表示され、価格チャートとの相関が一画面で確認できる

**実装上のポイント**:
- `useGeneration.js` が返す `generation.time_series` を直接 Recharts に渡すだけ
- 追加 API コール不要（既存レスポンスに `time_series` 含まれている）
- バックエンド変更ゼロ

### 10.2 アクセシビリティ — カラーインジケーターにテキストラベル追加（工数: 極小）

**なぜ**: 現在「安い/普通/高い」が色のみで表現されている。これが フロントエンド A に留まる唯一の理由。

- [x] `PriceIndicator.jsx`: 色リングに加えて "Cheap" / "Normal" / "Expensive" テキストを追加
  - 実装確認: line 32 `{level}` が既に "Cheap"/"Normal"/"Expensive" をテキスト表示済み
- [x] カラーはそのまま維持、テキストを追加するだけ（デザイン変更最小）

**完了条件**: スクリーンリーダーまたは色覚多様性ユーザーがテキストだけで価格水準を判断できる

---

## Phase 11: ML 価格予測（フル A/B テスト付き）

**なぜやるか**: 現在の `same_weekday_avg` モデルは p10/p50/p90 を返すが、精度を証明する仕組みがない。「モデルを作った」ではなく「精度を数値で改善した」を面接で語るために、バックテスト基盤を先に構築する。

### 11.1 バックテスト基盤（工数: 小）

- [ ] `models/forecast_accuracy.py`: `forecast_accuracy` テーブル
  - カラム: date, area, model_name, hour, predicted_sek_kwh, actual_sek_kwh, created_at
  - UNIQUE(date, area, model_name, hour)
- [ ] `db/migrations/`: Alembic マイグレーション
- [ ] `services/backtest_service.py`: スコアリング関数
  - 予測 vs 実績を比較して MAE / RMSE を計算
  - `score_forecast(db, date, area, model_name)` — 当日実績が揃った翌日に実行
- [ ] `GET /api/v1/forecast/accuracy?area=SE3&days=30` エンドポイント
  - model_name 別の MAE / RMSE を返す

**完了条件**: `same_weekday_avg` の過去 30日 MAE が数値で取得できる（ベースライン確立）

### 11.2 特徴量エンジニアリング（工数: 中）

- [ ] `services/feature_service.py`: 特徴量生成パイプライン
  - 時間帯（0-23）、曜日（0-6）、月（1-12）
  - 前日同時間帯の価格、前週同曜日の価格
  - Generation Mix: hydro_ratio, wind_ratio（当日分は前日の実績値を使用）
  - 季節エンコーディング（sin/cos 変換で cyclical feature）
- [ ] `scripts/build_feature_matrix.py`: 過去 N 日分の特徴量行列を CSV/DataFrame で出力
  - 動作確認用。Jupyter Notebook 不要
- [ ] テスト: 特徴量が NaN なく生成されることを確認（DST 境界日も含む）

**完了条件**: 過去 90日分の特徴量行列が生成できる

### 11.3 LightGBM モデル訓練（工数: 中）

- [ ] `requirements.txt` に `lightgbm` を追加（Lambda でも動く wheel あり）
- [ ] `services/ml_forecast_service.py`
  - 訓練: 最新 90日 − 最後 7日（テストセット）
  - 予測対象: 翌日 24時間の SEK/kWh
  - 出力: `build_forecast()` と同じ `{slots: [{hour, avg, low, high}], summary}` フォーマット
  - モデルバイナリは `/tmp/` にキャッシュ（Lambda コールド/ウォーム対応）
- [ ] `GET /api/v1/prices/forecast` に `model=lgbm` クエリパラメータを追加
  - `model=same_weekday_avg`（デフォルト、既存）/ `model=lgbm`（新規）
- [ ] バックテスト連携: 予測実行時に `forecast_accuracy` テーブルへ自動記録

**完了条件**: LightGBM の翌日予測が `same_weekday_avg` と同じ API フォーマットで返る

### 11.4 精度比較 UI（工数: 小）

- [ ] フロントエンド: Tomorrow タブに「Forecast accuracy」ミニカード
  - same_weekday_avg: MAE = X.X öre/kWh（過去 30日）
  - LightGBM: MAE = X.X öre/kWh（過去 30日）
  - 改善率: -XX%（LightGBM が優れていれば）
- [ ] モデル切り替えトグル（任意: 予測バンドを sam_weekday_avg / lgbm で切り替え）

**完了条件**: 「ML により MAE が X öre → Y öre に改善した」を画面上で証明できる

---

## Phase 12: 低優先度タスク（時間があれば）

### 12.1 README スクリーンショット配置
- [ ] `namazu-el.vercel.app` をブラウザで開き、スクリーンショットを撮影
- [ ] `docs/screenshot.png` に配置（フォルダがなければ作成）
- README の `![Namazu dashboard](docs/screenshot.png)` が表示されることを確認

### 12.2 EUR/SEK 動的レート（Riksbank API）
- [ ] Riksbank の SWEA API で当日の EUR/SEK を取得（認証不要）
- [ ] `config.py` の `eur_to_sek_rate = 11.0` を Riksbank API フォールバック構成に変更
  - API 取得成功 → 当日レート、失敗 → 11.0 にフォールバック
- [ ] Scheduler Lambda に日次レート取得を追加

### 12.3 Phase 8.1 — Intraday（IDA）重ね表示
- [ ] 既存の未チェックタスク（Phase 8.1 参照）

---

## Claude Code セッションの進め方

### 各セッション開始時に渡すもの
```
以下のファイルを読んでください:
- PROJECT_BRIEF.md（プロジェクトの目的と文脈）
- ARCHITECTURE.md（技術構成）
- DOMAIN_KNOWLEDGE.md（ドメイン知識）
- TASKS.md（このファイル — 現在の進捗）

現在のタスク: [タスク番号] を実装してください。
```

### セッション終了時の確認
- [ ] タスクの完了条件を満たしているか
- [ ] テストがあるか（あれば通っているか）
- [ ] TASKS.md のチェックボックスを更新したか
- [ ] 次のセッションに引き継ぐべき情報はあるか
