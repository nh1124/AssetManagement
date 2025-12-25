# 次世代金融資産管理システム設計書 (System Design 2.1)

アーキテクトとして、定義された戦略的要件（B/S・P/L統合、生活原価モデル、ゴールベース運用）を具現化するための、モダンで拡張性の高い設計を提案します。

コンセプトは **"Python-Native & Local-First"** です。

---

## 1. System Architecture (Component Diagram)

データフローの中心に「SQLite (Local DB)」を据え、計算ロジックとUIをPythonで統一します。

```mermaid
graph TD
    %% Define Styles
    classDef storage fill:#f9f,stroke:#333,stroke-width:2px;
    classDef logic fill:#9cf,stroke:#333,stroke-width:2px;
    classDef ui fill:#ff9,stroke:#333,stroke-width:2px;
    classDef external fill:#ddd,stroke:#333,stroke-dasharray: 5 5;

    subgraph "External World (Data Sources)"
        MF[MoneyForward / Bank CSVs]:::external
        YF[Yahoo Finance API<br>(yfinance)]:::external
        Man[User Manual Input<br>(Life Events / High-Value Assets)]:::external
        Excel[<b>Micro-Cost Input</b><br>(Excel/YAML)]:::external
    end

    subgraph "Docker Container / Local Env"
        subgraph "Ingestion Layer"
            Importer[<b>Data Importer</b><br>Pandas/Polars<br>Normalize CSVs]:::logic
            ConfigLoader[<b>Config Loader</b><br>Load Standard Costs to DB]:::logic
        end

        subgraph "Storage Layer"
            DB[(<b>SQLite DB</b><br>Assets / Market Data / Standard Costs)]:::storage
        end

        subgraph "Core Logic Layer"
            Valuator[<b>Valuation Engine</b><br>Mark-to-Market<br>FX Conversion]:::logic
            Depreciator[<b>Asset Lifecycle Mgr</b><br>Depreciation Calc]:::logic
            
            subgraph "Strategic Engine"
                CFAnal[<b>Cash Flow Analyzer</b><br>FCF / Burn Rate<br>Unit Economics]:::logic
                Sim[<b>Simulation Engine</b><br>Monte Carlo / Roadmap Gap]:::logic
            end
        end

        subgraph "Presentation Layer"
            Dash[<b>Streamlit Dashboard</b><br>Visualization & Interactive UI]:::ui
        end
    end

    %% Data Flow
    MF -->|Transaction/Balance CSV| Importer
    YF -->|Fetch Prices| Importer
    Excel -->|Standard Cost Params| ConfigLoader
    Man -->|Input Form| Dash
    Dash -->|Write Config/Goals| DB

    Importer -->|Write| DB
    ConfigLoader -->|Upsert| DB
    DB <-->|Read/Write| Valuator
    DB <-->|Read/Write| Depreciator
    DB <-->|Read Params| CFAnal
    
    Valuator -->|Asset Value| CFAnal
    CFAnal -->|Investable Capacity| Sim
    Depreciator -->|Real Asset Value| Valuator
    
    Valuator -->|B/S Data| Dash
    CFAnal -->|P/L & Savings Rate| Dash
    Sim -->|Probability/Gap| Dash
```

### 技術スタック選定理由

*   **Database: SQLite**
    *   サーバ構築不要。`assets.db` 1ファイルで完結し、バックアップも容易。
*   **Backend/Logic: Python (Pandas + Pydantic)**
    *   Pandasは時系列・金融計算に最適。Pydanticでデータの型安全性を保証。
*   **UI: Streamlit**
    *   Pythonのみで高速にダッシュボードを構築可能。MVP開発に最適。
*   **Infrastructure: Docker Compose**
    *   環境の再現性を確保。将来的なクラウド移行も容易。

---

## 2. Data Flow Strategy

### A. フロー(Flow) vs ストック(Stock) のハイブリッド管理
*   **Stock is King:** 銀行・証券口座の「残高」を正（Source of Truth）とする。
*   **Flow is Explanation:** 取引履歴は増減の「理由」として扱う。差分は `Adjustment` として自動処理。
*   **Logical Balance:** 実残高から、確定している将来負債（カード引き落とし予定等）を控除して表示。

### B. 外部データ取得・パラメータ管理
*   **Internal Data:** MoneyForward等の既存サービスからCSVを取得し、Importerで正規化。
*   **External Market Data:** `yfinance` を使用し、キャッシュ（DB保存）により重複取得を防止。
*   **Standard Cost (Micro-Costing):** 
    *   **Input:** ユーザーは `config/standard_costs.yaml` や Excelファイルを編集する。
    *   **Store:** システムはDBの `STANDARD_COST_PARAM` テーブルを参照する。これによりシミュレーションの再現性とパラメータの履歴管理を可能にする。

---

## 3. Step-by-Step Implementation Plan

### Step 1: Core DB & Data Modeling (所要目安: 1日)
*   **Tables:** `assets_master`, `balance_snapshot`, `market_data`, `life_goals`, `standard_costs`.
*   **Model:** Pydanticによるデータ構造定義。

### Step 2: Ingest Pipeline (所要目安: 2-3日)
*   **Function:** 各種CSV（MF, 銀行等）の正規化・Upsertロジックの実装。
*   **Goal:** スクリプト実行により、最新のB/SとP/L（実績）がDBに反映される状態。

### Step 3: Calculation Engine & Visualization (所要目安: 3-4日)
*   **Logic:** 通貨換算、含み益計算（Net Asset）、減価償却計算の実装。
*   **KPI Dash:** 総資産、Net Worth、貯蓄率、ロードマップ乖離率の可視化。

### Step 4: Advanced Simulation & Audit (所要目安: 週末)
*   **Forecasting:** モンテカルロ法を用いたゴール達成確率の算出。
*   **Purchase Audit:** 閾値（3万円）以上の購入検討時のトレードオフ分析UIの実装。

---

### Next Action
この設計に基づき、Step 1の具体的な **「DBスキーマ定義」** と **「ディレクトリ構成」** の作成に進みます。