# 次世代金融資産管理システム データモデル定義書 (Conceptual Data Model 1.2)

## 1. エンティティ関係図 (ER Diagram)

```mermaid
erDiagram
    %% --- Master Data ---
    ASSET_CLASS {
        string code PK "CASH, STOCK, DURABLE, CRYPTO"
        string name
        boolean is_depreciable "減価償却対象か"
        boolean is_market_linked "市場連動するか"
    }

    CURRENCY {
        string code PK "JPY, USD"
        string symbol
    }

    LIFE_GOAL {
        int id PK
        string name "老後資金, 住宅購入"
        decimal target_amount
        date target_date
        string priority "High, Medium, Low"
    }

    TRANSACTION_CATEGORY {
        int id PK
        string name "食費, 住居費, 趣味"
        boolean is_essential "基礎生活費か(FCF計算用)"
        string parent_category_id FK
    }

    %% --- Account & Holdings ---
    ACCOUNT {
        int id PK
        string name "A銀行, B証券, 自宅"
        string institution
        string tax_type "TAXABLE, NISA, IDECO, CASH"
    }

    ASSET_POSITION {
        int id PK
        int account_id FK
        string asset_class_code FK
        string ticker_symbol "AAPL, JPY, MACBOOK_2025"
        string name
        decimal quantity "株数, 個数, 金額(現金の場合)"
        decimal acquisition_price "取得単価"
        date acquisition_date "購入日"
        int lifespan_days "耐用日数 (耐久財用)"
        decimal salvage_value "残存簿価 (耐久財用)"
        string currency_code FK
        string status "ACTIVE, SOLD, DISPOSED"
        int origin_transaction_id FK "購入時の取引ID(Traceability)"
    }

    %% --- Time Series / Market ---
    MARKET_PRICE {
        string ticker_symbol PK
        date date PK
        decimal close_price
        string currency_code
    }

    EXCHANGE_RATE {
        string from_currency PK
        string to_currency PK
        date date PK
        decimal rate
    }

    %% --- History / Snapshot ---
    TRANSACTION {
        int id PK
        date transaction_date
        string type "INCOME, EXPENSE, TRANSFER, BUY, SELL, DEPRECIATION"
        int from_account_id FK
        int to_account_id FK
        decimal amount
        string currency_code
        string description
        int category_id FK "費目分類(FCF/KPI用)"
        int asset_position_id FK "減価償却/売却対象の資産ID"
        boolean is_logical_only "論理残高計算用フラグ"
    }

    BALANCE_SNAPSHOT {
        date date PK
        int position_id PK FK
        decimal quantity
        decimal unit_price_raw "原資産通貨での単価"
        decimal valuation_jpy "円換算後の評価額"
        decimal cost_basis_jpy "取得原価(円)"
        decimal estimated_tax_jpy "含み益に対する推定税額"
    }

    %% --- Strategy / Planning ---
    STANDARD_COST_PARAM {
        string category_key PK "FOOD_DAILY, RENT"
        decimal unit_cost
        string unit "PER_DAY, PER_MONTH"
        date updated_at "パラメータ更新日(履歴管理)"
        string source_file "取込元のファイル名(Traceability)"
    }
    
    GOAL_ALLOCATION {
        int goal_id PK FK
        int position_id PK FK
        decimal allocation_ratio "この資産の何%をこのゴールに割り当てるか"
    }

    %% Relationships
    ACCOUNT ||--|{ ASSET_POSITION : holds
    ASSET_CLASS ||--|{ ASSET_POSITION : classifies
    ASSET_POSITION ||--o{ BALANCE_SNAPSHOT : has_history
    ASSET_POSITION }|--|| GOAL_ALLOCATION : allocated_to
    LIFE_GOAL ||--|{ GOAL_ALLOCATION : consists_of
    TRANSACTION }|--|| ACCOUNT : affects
    TRANSACTION }|--|| TRANSACTION_CATEGORY : classified_as
    TRANSACTION ||--o{ ASSET_POSITION : creates_or_modifies
```

---

## 2. 改訂ポイント (Updates from 1.1)

### 2.1. Tax Classification (税区分によるNet Worth精緻化)
*   **`ACCOUNT.tax_type`**: 口座ごとに税区分を定義。
    *   `TAXABLE`: 特定口座・一般口座。利益に対して課税。
    *   `NISA`: 新旧NISA口座。利益は非課税。
    *   `IDECO`: 確定拠出年金。受取時まで課税繰り延べ（本システム上は簡易的に非課税扱い、または出口戦略ロジックで対応）。
    *   `CASH`: 預金・現金。為替差益以外は原則非課税（利子は源泉徴収済みのため考慮不要）。

### 2.2. Estimated Tax in Snapshot
*   **`BALANCE_SNAPSHOT.estimated_tax_jpy`**:
    *   スナップショット保存時に、`Valuation Engine` が `tax_type` と含み益に基づいて計算した「推定税額」を記録します。
    *   **Net Asset Value (NAV)** = `valuation_jpy` - `estimated_tax_jpy` で算出可能になります。

### 2.3. Micro-Costing Source (生活原価の管理場所)
*   **`STANDARD_COST_PARAM`**:
    *   Runtime StoreとしてDBテーブルを正とします。
    *   **Input Interface:** `config/standard_costs.yaml` や Excelファイル。
    *   **Flow:** ユーザーがファイルを編集 -> `Ingestion Layer` がDBへロード -> `Simulation Engine` がDBを参照して計算。これにより、編集の容易性と計算の堅牢性を両立します。

---

## 3. 主要エンティティの定義

### 3.1. ASSET_POSITION (統一資産モデル)
全ての「価値あるもの」を同一形式で管理します。

*   **Cash:** `Ticker = JPY`, `Lifespan = NULL`.
*   **Stocks/Crypto:** `Ticker = AAPL`, `IsMarketLinked = True`. `Valuation Engine` により定期的に時価更新。
*   **Durable Assets (耐久消費財):** `Ticker = MACBOOK`, `Lifespan = 1825(5年)`. `Depreciator` により購入日から日次で評価額を減少。

### 3.2. TRANSACTION (P/L & 論理残高)
*   **Logical Balance:** 未来の日付かつ `is_logical_only = True` のレコード（クレカ引き落とし予定等）を含めて集計することで、将来の資金ショートを予測。
*   **TCO Integrated P/L:** 3万円以上の購入は `BUY`（資産化）として処理。代わりに `DEPRECIATION`（減価償却）という仮想トランザクションを生成し、P/L上の「真の月次コスト」を算出。

### 3.3. LIFE_GOAL & GOAL_ALLOCATION (Personal ALM)
*   **Virtual Bucket:** 物理的な口座の仕切りに頼らず、データ上で資産ポジションを各ゴールに割り当て。
*   **Mark-to-Goal:** 各ゴールの現在価値（資産評価額の合計）と目標額のギャップを常に監視。

---

## 4. データフローとの整合性

*   **Ingestion:** MoneyForward等のCSVから `TRANSACTION` と `BALANCE_SNAPSHOT` を生成。
*   **Valuation:** `MARKET_PRICE` と `EXCHANGE_RATE` を用いて `BALANCE_SNAPSHOT` の円換算額を更新。
*   **Simulation:** `LIFE_GOAL` と `STANDARD_COST_PARAM` を元に、将来の `BALANCE_SNAPSHOT` の推移を予測。