# DOMAIN_KNOWLEDGE.md

# Namazu — ドメイン知識：日本のFITとスウェーデンの電力市場

> このドキュメントは、実装時のビジネスロジックの根拠と、面接での説明材料を兼ねる。
> TRENDEの機密情報やコードは一切含まない。公知の情報と概念的な理解のみ。

---

## 1. 日本の太陽光発電・売電の仕組み（Shinの実務経験）

### 1.1 FIT（固定価格買取制度）の基本構造

FIT（Feed-in Tariff）は、再生可能エネルギーの普及を目的に2012年に開始された制度。家庭用太陽光発電（10kW未満）の場合、発電した余剰電力を10年間固定価格で電力会社に売電できる。

```
太陽光パネル → 発電 → 自家消費（優先） → 余剰分 → 電力会社が固定価格で買取
```

買取価格の推移（家庭用10kW未満）：

- 2012年: 42円/kWh
- 2015年: 33円/kWh
- 2019年: 24円/kWh
- 2024年: 16円/kWh
- トレンド: 毎年下がり続けている

### 1.2 卒FIT問題

2019年11月以降、FIT期間（10年）を満了した家庭が順次発生（「卒FIT」）。卒FIT後の選択肢：

1. **大手電力会社に売電**: 7〜8円/kWh程度の変動価格。FIT期間中の1/5以下
2. **新電力に売電**: 各社が競争的な買取価格を提示（8〜12円/kWh程度）
3. **自家消費を最大化**: 蓄電池を導入し、売電せずに自分で使う

経済合理性から「売るより自家消費した方が得」という構造に変化。これが蓄電池需要とP2P取引の動機。

### 1.3 TRENDEでの売電バックエンドの概念構造

TRENDEの具体的なコードやシステム構成は記載しない。以下は公知情報と一般的な概念に基づく、売電管理システムの典型的なバックエンド構造。

```
[データ取得層]
  スマートメーター → 30分単位の発電量・消費量データ
  買取価格 → FIT固定価格（経産省の公示価格）をスクレイピングで取得

[計算層]
  余剰電力量 = 発電量 − 自家消費量
  売電収益 = 余剰電力量 × 買取価格（固定）
  ※FIT下では価格が固定なので、計算は単純な掛け算

[請求・精算層]
  月次で売電収益を集計
  ユーザーへの支払い計算
  請求書生成

[ユーザー向けUI層]
  マイページ: 発電量、消費量、売電量、収益の可視化
  月次・日次のグラフ表示
```

**ポイント：FITの場合、価格が固定なので「いつ売るか」の判断は不要。**
発電したら即売電、それだけ。これがスウェーデンのスポット市場との最大の違い。

### 1.4 P2P電力取引の概念（TRENDEの公開情報に基づく）

TRENDEは伊藤忠の子会社として、P2P電力取引の商用化を進めている（2024年9月、JA全農と群馬県で商用サービス開始）。

P2Pの基本的な仕組み（公開情報）：

- 太陽光発電家庭の余剰電力を、近隣の需要家に直接販売
- AIによる需給予測でマッチングを最適化
- ブロックチェーン技術で取引を記録
- 物理的には同じ送電網を使用（電気に「色」はない）
- 経済的な付加価値は「地産地消」「環境価値」「コミュニティ形成」

**正直な評価：**
P2Pの純粋な経済合理性は限定的。JEPXスポット市場が既に存在する中で、個人間取引の経済的メリットは「送電コストの一部回避」と「環境価値のプレミアム」に限られる。ただし、伊藤忠のSmart Star蓄電池エコシステムとの組み合わせで、HEMSプラットフォームとしての価値がある。

---

## 2. スウェーデンの電力市場

### 2.1 市場構造の全体像

```
[発電] → [卸売市場: Nord Pool] → [小売: 電力会社] → [消費者]
                                        ↑
                                  [送電網: DSO/TSO]
                                  (別契約・別請求)
```

スウェーデンの消費者は毎月2つの請求書を受け取る：

1. **Elnät（送電網料金）**: 住んでいる地域で自動的に決まる。ヨーテボリならGöteborg Energi。選べない
2. **Elhandel（電力小売料金）**: 自由に選べる。Tibber、Greenely、Vattenfall等、約140社

### 2.2 価格ゾーンと価格形成

スウェーデンは4つのbidding area（価格ゾーン）に分かれている：

- **SE1（Luleå）**: 北部。水力発電の余剰で最も安い
- **SE2（Sundsvall）**: 中北部
- **SE3（Stockholm / Göteborg）**: 中南部。人口が集中し、需要が高い。Namazuのターゲット
- **SE4（Malmö）**: 南部。大陸（ドイツ等）の価格影響を受けやすく最も高い

Nord Poolでの日前市場（day-ahead market）：

- 毎日12:00〜13:00 CET頃に翌日の24時間分（15分単位 or 1時間単位）の価格が決定
- 供給と需要の入札によるオークション方式
- 価格はEUR/MWhで公表され、SEK/kWhに換算して消費者に提供

### 2.2-A 北欧電力市場の3層構造（Namazuが可視化する範囲）

実際の電力市場はDay-aheadだけではなく、3つの時間軸で成り立っている：

```
時間軸                    市場                  Namazu実装
─────────────────────────────────────────────────────────
翌日 13:00 CET          Day-ahead (Elspot)    ✅ ENTSO-E A44
                         Nord Pool オークション   /prices/today, /tomorrow

翌日〜当日              Intraday (XBID)       ❌ API未公開（SE3）
                         連続取引（15分ごと入札）  ENTSO-E processType=A47は
                                                DA価格と同一データを返す

当日 15分後              Balancing (SVK管轄)   ✅ eSett EXP14
                         アンバランス清算価格     /prices/balancing
                         upReg(A05) / downReg(A04)
                         データラグ: ~5〜6h
─────────────────────────────────────────────────────────
```

**各層の意味と相互関係**

| 市場層 | 誰が管理 | 価格形成の仕組み | 何を反映するか |
|--------|---------|----------------|--------------|
| Day-ahead | Nord Pool | 供給者・小売業者の翌日入札オークション | 翌日の大まかな需給予測 |
| Intraday | Nord Pool (XBID) | 連続取引（Amazonの注文書に近い） | Day-ahead後の需給変化 |
| Balancing | TSO (Svenska kraftnät) | 15分ごとに実際の需給ギャップを清算 | **グリッドの実際の需給ひっ迫** |

**アンバランス価格（Balancing）が面白い理由**

Day-ahead価格は「予測価格」、アンバランス価格は「実際にかかったコスト」。
例：寒波で予測を超えて需要が急増した場合、Short価格（A05）がDay-aheadの2〜3倍に跳ね上がる。
これはグリッドが「想定外の状況」に直面したことを示すシグナルであり、
VPP・デマンドレスポンス・蓄電池最適化の「なぜ今動くべきか」を説明する根拠になる。

**インタビューで「Tibberのエンジニアが面白いと思うポイント」**:
「Namazuは Day-ahead の可視化だけでなく、アンバランス市場のデータも重ねて表示できる。
これにより、『昨日の17時に価格スパイクが起きたのはなぜか』を日前価格との比較で説明できる。
これは単なる価格ダッシュボードではなく、グリッド状況の解説ツールとしての位置付け。」

### 2.3 電力契約の種類


| 契約タイプ       | スウェーデン語                    | 仕組み                 | 向いている人             |
| ----------- | -------------------------- | ------------------- | ------------------ |
| 固定価格        | Fast pris                  | 1〜5年間、kWhあたり固定      | 安定志向、予算管理重視        |
| 月間変動        | Rörligt pris (månadsmedel) | 月平均スポット価格           | 以前の主流              |
| **15分単位動的** | **Kvartspris**             | **15分ごとにスポット価格が変動** | **Namazuのターゲット** |


Kvartspris（15分単位動的価格）は2025年にEU基準に基づいて導入された新しい契約形態。TibberとGreenely がこの契約に特化している。

**固定価格契約のUI初期値について（Namazuの実装メモ）**

ConsumptionSimulator の「Fixed price」初期値 **1.80 SEK/kWh** は、以下の計算から導出したプレースホルダー：

```
固定契約価格 ≈ (スポット平均 + 非スポット固定費) × 1.25 (VAT)
非スポット固定費 = マージン(0.08) + 送電料(0.30) + エネルギー税(0.48) + エルサート(0.03) = 0.89 SEK/kWh

スポット平均 0.55 SEK/kWh 想定:
  (0.55 + 0.89) × 1.25 ≈ 1.80 SEK/kWh
```

- スポット相場が上下すれば固定価格も変わる。実際の値は **請求書（faktura）** に記載の öre/kWh を確認する
- SE3 の長期固定契約の実勢値（2024-2026年）: 概ね **1.20〜2.20 SEK/kWh**
- 自分のGöteborg Energi契約のように「月平均スポット×消費量」型は固定価格ではなく月間変動（Rörligt månadsmedel）に相当する

### 2.4 電力価格の構成要素（SE3の場合）

消費者が実際に払う電力価格の内訳：

```
支払い = スポット価格 + 電力会社マージン + 送電料 + エネルギー税 + 電力証書 + VAT(25%)
```

具体的な数値感（2025年、SE3の平均的な日）：

- スポット価格: 30〜150 öre/kWh（時間帯により大きく変動）
- 電力会社マージン: 5〜10 öre/kWh（Tibber: 8.6 öre, Greenely: 同程度）
- 送電料（elnät）: 20〜40 öre/kWh（固定的、Göteborg Energiが設定）
- エネルギー税: 43.9 öre/kWh（2025年）
- 電力証書: 0.5〜1 öre/kWh
- VAT: 上記合計の25%

**→ 合計: 約150〜300 öre/kWh（1.5〜3.0 SEK/kWh）**

### 2.5 マイクロプロデューサー（家庭用太陽光発電）

スウェーデンでの家庭用太陽光の売電：

- 余剰電力は契約している電力小売会社（elhandelsbolag）に売電
- 売電価格 = スポット価格（+ 会社によるボーナス。Greenely: +5 öre/kWh）
- **2025年まで**: 60 öre/kWh の税控除（skattereduktion）あり（年間最大18,000 SEK）
- **2026年1月〜**: この税控除が完全廃止

税控除廃止の影響（年間5,000kWh売電する家庭の例）：

```
2025年まで:
  売電収益 = 5,000 × 0.40 SEK（スポット平均） = 2,000 SEK
  税控除   = 5,000 × 0.60 SEK = 3,000 SEK
  合計     = 5,000 SEK/年

2026年以降:
  売電収益 = 5,000 × 0.40 SEK = 2,000 SEK
  税控除   = 0
  合計     = 2,000 SEK/年（60%減）
```

→ 自家消費を最大化する経済的インセンティブが劇的に強まる。日本の卒FITと同じ構造。

---

## 3. 構造の比較：日本 ↔ スウェーデン

### 3.1 共通する構造的変化


|             | 日本（卒FIT）        | スウェーデン（税控除廃止）                   |
| ----------- | --------------- | ------------------------------- |
| **いつ**      | 2019年11月〜順次     | 2026年1月〜一斉                      |
| **何が変わる**   | 固定高額買取 → 低額変動価格 | 税控除あり → 税控除なし                   |
| **売電収入の変化** | 約1/5に減少         | 約60%減少                          |
| **消費者の反応**  | 蓄電池導入、自家消費最大化   | 蓄電池導入（前年比34%増）、自家消費最大化          |
| **市場の動き**   | P2P取引、HEMS、VPP  | VPP（Tibber Grid Rewards）、スマート充電 |


### 3.2 異なる点


|            | 日本                       | スウェーデン                             |
| ---------- | ------------------------ | ---------------------------------- |
| **価格の動き方** | 卒FIT後も基本的に固定的（大手電力の買取価格） | 15分単位で変動（Nord Poolスポット）            |
| **最適化の余地** | 「売るか、自家消費するか」の2択         | 「いつ売るか、いつ蓄電するか、いつ自家消費するか」のタイミング最適化 |
| **データの粒度** | 30分単位（スマートメーター）          | 15分単位（Kvartspris）                  |
| **P2Pの状況** | 商用化段階（TRENDE + JA全農）     | 法的に未整備（EU指令の国内法化待ち）                |
| **暖房との関係** | 電力と暖房は独立                 | 地域暖房（fjärrvärme）が別系統で存在            |


### 3.3 バックエンドの設計への影響

日本のFITバックエンドとスウェーデン向けの違い：

```
[日本のFITバックエンド]
  売電情報取得: スクレイピングで各WEBで公開される情報を取得（毎日）＝売電収入
  発電量取得: 各家庭のスマートメータから4G回線で送信される発電情報を受信
  計算: 発電量 - 売電電力量（FIT）＝ 自家消費量＋基本使用量など
  売電収入 × 固定価格 = 売電収益
  最適化: なし（価格が固定なので最適化の余地がない）
  更新頻度: 日次〜月次

[スウェーデン向けバックエンド（Namazu）]
  価格取得: ENTSO-E APIからスポット価格を取得（日次、翌日分）
  計算: 各15分スロットごとに最適な行動を判断
  最適化: 「売電 vs 蓄電 vs 自家消費」の動的最適化
  更新頻度: 日次（価格）、リアルタイム（ダッシュボード表示）
```

**これが「同じ問題を、価格が動的になることで再設計する」というプロジェクトの核心。**

---

## 4. Namazuの実装に必要なドメイン計算

### 4.1 Layer 1: 消費最適化

**「いつ電気を使えば一番安いか」の計算**

```python
# 基本ロジック（概念）
def find_cheapest_hours(prices: list[PriceSlot], duration_hours: float) -> TimeWindow:
    """
    指定時間分の連続する最安時間帯を見つける
    例: duration_hours=2 → 2時間連続で最も安い開始時刻を返す
    """
    slots_needed = int(duration_hours * 4)  # 15分スロット数
    min_cost = float('inf')
    best_start = None
    
    for i in range(len(prices) - slots_needed + 1):
        window_cost = sum(p.price_sek for p in prices[i:i+slots_needed])
        if window_cost < min_cost:
            min_cost = window_cost
            best_start = prices[i].timestamp
    
    return TimeWindow(start=best_start, avg_price=min_cost/slots_needed)
```

**固定価格 vs ダイナミック価格の月額比較**

```python
def compare_contracts(monthly_kwh: float, fixed_price: float, spot_prices: list) -> Comparison:
    """
    同じ消費量で、固定価格契約とダイナミック価格契約のコスト差を計算
    前提: ダイナミック価格の場合、消費は均等に分散（最適化なし）
    """
    fixed_cost = monthly_kwh * fixed_price
    
    # ダイナミック: 各時間帯の平均スポット価格で計算
    avg_spot = sum(p.price_sek for p in spot_prices) / len(spot_prices)
    dynamic_cost = monthly_kwh * (avg_spot + MARGIN + GRID_FEE + ENERGY_TAX) * VAT_RATE
    
    # 最適化した場合: 安い時間帯に消費を集中
    # （実際の節約効果のシミュレーション）
    optimized_cost = calculate_optimized_cost(monthly_kwh, spot_prices)
    
    return Comparison(
        fixed=fixed_cost,
        dynamic_no_optimization=dynamic_cost,
        dynamic_optimized=optimized_cost
    )
```

### 4.2 Layer 2: 太陽光発電シミュレーション

**発電量の推定**

```python
def estimate_solar_generation(
    panel_kwp: float,          # パネル容量 (kWp)
    radiation_wh_m2: float,    # 全天日射量 (Wh/m²) — SMHIから取得
    performance_ratio: float = 0.80  # システム効率
) -> float:
    """
    太陽光発電量の簡易推定
    
    kWp: パネルの定格出力。1kWpは標準条件(1000W/m²)で1kW発電
    radiation: 実際の日射量。スウェーデンの夏は長日照、冬は極端に少ない
    performance_ratio: 温度損失、配線損失、経年劣化等を含むシステム全体の効率
    """
    # kWh = kWp × (radiation / 1000) × performance_ratio
    generation_kwh = panel_kwp * (radiation_wh_m2 / 1000) * performance_ratio
    return generation_kwh
```

ヨーテボリ（SE3）の月別日射量の目安（kWh/m²/day）：

- 1月: 0.3, 2月: 0.8, 3月: 1.8, 4月: 3.5
- 5月: 5.0, 6月: 5.5, 7月: 5.2, 8月: 4.2
- 9月: 2.5, 10月: 1.2, 11月: 0.4, 12月: 0.2

→ 冬（11-1月）はほぼ発電しない。夏（5-7月）に年間発電量の大部分を稼ぐ。

**売電 vs 蓄電 vs 自家消費の最適化**

```python
def optimize_solar_usage(
    generation_kwh: list[float],    # 15分ごとの発電量
    consumption_kwh: list[float],   # 15分ごとの消費量
    spot_prices: list[float],       # 15分ごとのスポット価格
    battery_kwh: float,             # 蓄電池容量 (0 = なし)
    battery_soc: float = 0.0        # 蓄電池の初期充電率
) -> OptimizationResult:
    """
    各15分スロットで最適な行動を判断:
    
    1. 発電 > 消費の場合（余剰あり）:
       - スポット価格が高い → 売電（即座にグリッドに売る）
       - スポット価格が低い + 蓄電池あり → 蓄電（後で高い時に使う/売る）
       - 蓄電池なし → 売電（選択肢がない）
    
    2. 発電 < 消費の場合（不足）:
       - 蓄電池に余裕あり + スポット価格が高い → 蓄電池から放電
       - スポット価格が低い → グリッドから購入
    
    簡易版では「閾値ベース」のルール:
    - スポット価格 > 日平均 × 1.2 → 売電/放電優先
    - スポット価格 < 日平均 × 0.8 → 充電/購入優先
    - それ以外 → 自家消費優先
    """
    # 実装はservices/optimizer.pyで行う
    pass
```

### 4.3 税控除廃止の影響シミュレーション

```python
def compare_tax_credit_impact(
    monthly_sold_kwh: float,
    spot_prices: list[float],
    panel_kwp: float
) -> TaxCreditComparison:
    """
    2025年（税控除あり）vs 2026年（税控除なし）の年間収益比較
    
    税控除の仕組み（2025年まで）:
    - 売電したkWh × 60öre = 税控除額
    - ただし、買電したkWhを上限とする（売電 ≤ 買電の分しか控除されない）
    - 年間上限: 18,000 SEK
    
    2026年以降:
    - 税控除 = 0
    - 売電収益 = スポット価格のみ
    """
    spot_revenue = sum(kwh * price for kwh, price in zip(sold_per_slot, spot_prices))
    tax_credit = min(monthly_sold_kwh * 0.60 * 12, 18000)  # 年間上限
    
    return TaxCreditComparison(
        with_credit=spot_revenue + tax_credit,
        without_credit=spot_revenue,
        difference=tax_credit,
        recommendation="蓄電池導入で自家消費率を上げることを推奨"
    )
```

---

## 5. スウェーデン特有の概念（面接で聞かれた場合の備え）

### 5.1 Fjärrvärme（地域暖房）

- ヨーテボリのアパートの90%が接続
- Göteborg Energiが1,000km超のパイプ網で温水を配送
- 熱源の80%は廃棄物焼却・製油所の余剰熱（リサイクルエネルギー）
- **電力市場とは別系統**。Namazuのスコープ外だが、文脈として理解しておく
- 2027年から効果ベース（effektbaserad）の料金体系に移行予定

### 5.2 VPP（仮想発電所）

- 多数の小さな電力資源（蓄電池、EV、ヒートポンプ等）をソフトウェアで束ねる
- Tibber Grid Rewards: 家庭用バッテリーをVPPとして運用し、バランシング市場で収益化
- NamazuのLayer 2は、VPPの「個人側のダッシュボード」に相当する位置付け
- 将来的な拡張としてVPP連携を言及できる（実装はスコープ外）

### 5.3 Bidding Area（価格ゾーン）

- スウェーデンは4ゾーン（SE1〜SE4）。北ほど安く、南ほど高い
- 理由: 北部に水力発電が集中し、南部に需要が集中。送電容量に制約がある
- NamazuはSE3（ヨーテボリ）にフォーカスするが、ゾーン切り替えは容易に実装可能

### 5.4 Prosumer（プロシューマー）の価格ギャップ問題

- 売電価格: スポット価格（30〜50 öre/kWh）
- 購入価格: スポット + マージン + 送電料 + 税 + VAT（150〜300 öre/kWh）
- 差が3〜6倍ある → 「売るより自分で使った方が得」
- EU指令でエネルギーシェアリングが認められれば、この差を縮める可能性がある
- スウェーデンではまだ法整備が追いついていない（2025年時点）

### 5.5 電力市場の価格透明性 — 誰が何を見えるか

電力市場は「層ごと」に価格の見え方がまったく異なる。混乱しやすい重要な区別。

#### イントラデイ市場（XBID）— 株式市場に近い

```
Nord Pool Intraday / XBID（Cross-Border Intraday）
→ Day-ahead確定後〜配送1時間前まで、連続取引
→ 注文板（買い板・売り板）がリアルタイムに存在
→ マッチングで価格が決まる（株式と同じメカニズム）
→ 【制約】板情報にアクセスできるのはBRP・ライセンス取得済み参加者のみ
→ 【公開】取引終了後の約定価格はNord Poolが遅延公開
```

つまりイントラデイ価格は「リアルタイムで見えるが、見えるのは市場参加者だけ」。

#### バランシング市場 — 行政命令＋事後精算

```
SVKが「今、電気が足りない → 火力発電所A、出力上げろ」と命令
→ 発電所Aが事前入札した価格で約定
→ eSett が15分間の精算価格を算出・公開（~5〜6時間後）
```

注文板は存在しない。SVKの内部判断であり、価格は事後にしか確定しない。

#### 小規模発電者（家庭用太陽光）が見えるもの

| 情報 | いつわかるか | ソース |
|------|------------|--------|
| 明日の24時間スポット価格 | 前日13:00 CET以降 | Tibber API / ENTSO-E |
| 今日の現在時刻スポット価格 | 前日に確定済み（リアルタイム更新ではない） | Tibber API |
| イントラデイ板情報 | 原則不可（BRP専用） | Nord Pool会員のみ |
| 自分が今売るといくらか | 前日確定のスポット価格で計算可 | Tibber/Greenely アプリ |
| バランシング価格 | ~5〜6時間後（eSett） | eSett EXP14 / Namazu |

#### Tibber API が公開しているもの

TibberはGraphQL APIで顧客向けに当日スポット価格を提供している：

```graphql
query {
  viewer {
    homes {
      currentSubscription {
        priceInfo {
          current { total startsAt }  # 今の時間帯の価格
          today { total startsAt }    # 今日の24時間分
          tomorrow { total startsAt } # 翌日分（13:00 CET以降）
        }
      }
    }
  }
}
```

これはDay-aheadスポット価格（前日確定済み）をユーザーに見やすく提供しているだけ。
イントラデイやバランシングのリアルタイム価格ではない。

#### なぜ小規模発電者はイントラデイ価格を活用できないか（構造的制約）

| 障壁 | 内容 |
|------|------|
| 計量インフラ | スマートメーターでも15分〜1時間単位の計量が上限 |
| 精算サイクル | ネット会社・eSett の精算処理が日次〜月次 |
| 制御の自由度 | 太陽光パネルは「今発電するな」と制御できない |
| 規制 | 100kW未満は簡易精算が義務付け（リアルタイム精算は義務なし） |

#### VPPが本当に価値を出す場面

制御可能なリソース（蓄電池・EV・ヒートポンプ）を持つ場合：

- **Tibber Grid Rewards / Flower（スウェーデン VPP）**: 家庭用蓄電池をFCR/mFRR市場に参加させ収益を分配
- **モデルの違い**: 「今この価格で売れる」ではなく「予備力として待機する対価をもらう」
- **情報の非対称性を解消**する方向のサービスが今後の競争軸

**結論**: 小規模発電者が"リアルタイム価格"を活かして行動最適化するには、まず計量・精算インフラの整備が前提。電力市場のデジタル化はまだ発展途上（2025年時点）。

---

## 6. 面接で使えるドメイン知識のQ&A

### Q: "What's the difference between FIT and spot market pricing?"

A: "FIT guarantees a fixed price per kWh for a set period — typically 10 years in Japan. The producer doesn't need to think about timing or market conditions. Spot pricing, like Sweden's Kvartspris, changes every 15 minutes based on supply and demand at Nord Pool. This creates both risk and opportunity — you can lose money selling at the wrong time, but you can also optimize by shifting when you sell or consume."

### Q: "Why is the micro-producer tax credit removal a big deal?"

A: "It's essentially Sweden's version of Japan's FIT expiry. The tax credit was 60 öre per kWh sold — often more than the spot price itself. Without it, solar ROI drops significantly, and the economic incentive flips from 'sell everything' to 'consume as much as possible yourself.' This drives demand for batteries and smart optimization, which is exactly what companies like Tibber and Greenely are building products around."

### Q: "How does your experience in Japan apply to the Swedish market?"

A: "The backend structure is fundamentally the same — data ingestion, price calculation, billing, user dashboards. The key difference is that Japan's fixed pricing makes the calculation trivial: quantity times price. Sweden's dynamic pricing adds a time dimension to every calculation. Instead of 'how much did you sell this month,' it becomes 'how much did you sell in each 15-minute window, and what was the price in each of those windows.' That's a more interesting engineering problem, but the data pipeline and system architecture patterns are directly transferable."

### Q: "What would you do differently if you rebuilt your Japanese system today?"

A: "I'd design for dynamic pricing from day one. Japan is also moving toward more market-based mechanisms — JEPX spot prices are increasingly relevant for post-FIT households. A system built on fixed pricing assumptions needs significant refactoring to handle time-varying prices. The API-first, event-driven architecture I'm using in Namazu is what I wish we'd had from the start."

### Q: "What are imbalance prices and why does Namazu show them?"

A: "Imbalance prices are the prices used to settle BRPs (Balance Responsible Parties) who deviated from their nominated schedules. Every 15 minutes, after supply and demand have played out in real time, SVK determines the regulation direction and price.

I show two series on top of the day-ahead chart: the up-regulation price (what short BRPs pay — can spike 2–3× day-ahead during grid stress) and the down-regulation price (what over-generating BRPs receive — often near zero or even negative when there's surplus). The gap between them, and the gap vs. day-ahead, is a direct measure of how unexpected the grid conditions were.

When a price spike appears on the balancing chart that isn't in the day-ahead, that's the grid signaling unexpected stress — exactly the kind of event where a smart home appliance should have shifted its load. That's the VPP thesis made visible in a single chart."

### Q: "Why did you use eSett instead of ENTSO-E A85 for balancing prices?"

A: "I started with ENTSO-E A85 and it worked, but I then discovered eSett's Open Data API — eSett is the Nordic balance settlement institution that actually manages imbalance settlement across Sweden, Finland, Norway, and Denmark. They expose the data directly via a public REST API with no API key required.

The key advantage is data freshness: eSett EXP14 lags about 5–6 hours behind real time, vs. ENTSO-E A85 which lags ~12 hours. Since the main value of showing imbalance prices is to reveal 'what actually happened today,' cutting the lag in half materially improves the usefulness.

I also tried SVK Mimer — SVK's own statistics portal — but found it only covers reserve products (FCR, mFRR, aFRR) and doesn't expose the imbalance settlement prices via its public API.

As for intraday (IDA): ENTSO-E's processType=A47 returns identical data to day-ahead for SE3. Nordic intraday trading happens via XBID continuous market, and XBID clearing prices aren't published through ENTSO-E's public REST API. So balancing prices are both the available and the more informative option."

### Q: "Can a prosumer see real-time electricity prices to decide when to sell?"

A: "It depends on which layer of the market you mean. The day-ahead spot price is determined by Nord Pool the afternoon before and is fully public — Tibber's API exposes it, and that's what most prosumers act on. So for a fixed generation source like rooftop solar, you do know the price 12–24 hours ahead, which is sufficient for most decisions.

The intraday market (XBID) does operate like a stock exchange with a live order book — bids and asks, continuous matching — but order book access is restricted to licensed BRPs. The cleared prices are published by Nord Pool with a delay, after trading closes for each window.

Balancing prices are different in nature: they're not an order book at all. SVK issues activation commands to regulation providers, and the settlement price is only calculated and published by eSett about 5–6 hours after the fact. So you can never see 'current balancing price' in real time.

In practice, small prosumers can't leverage intraday prices anyway — their metering, settlement cycles, and lack of flexible generation make it structurally impossible. Where VPPs add value is for controllable assets like batteries or EVs: Tibber Grid Rewards, for instance, aggregates home batteries and participates in FCR/mFRR reserve markets on behalf of households."

### Q: "What's the difference between upRegPrice and downRegPrice in your chart?"

A: "These are the two ends of the balancing market in any given 15-minute interval. The up-regulation price is what SVK paid to activate more generation — or what a BRP who was short (had a deficit) must pay. The down-regulation price is what SVK paid to reduce generation — what a BRP who was long (had a surplus) receives.

Both can exist in the same interval because the grid can have regional imbalances simultaneously: one area may be short while another is long, requiring counter-activation to manage congestion. Since Nordic SIB (Single Imbalance Balance) was introduced in April 2022, both short and long BRPs are settled at a single imbalance price, which equals the up-regulation price when the system's net direction is short."