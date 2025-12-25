# 次世代金融資産管理システム ディレクトリ構成定義 (Project Structure 1.1)

本プロジェクトは、Python-NativeかつLocal-Firstな設計に基づき、拡張性と保守性を両立した以下のディレクトリ構成を採用します。

```text
asset_management_ver2/
├── docker-compose.yml         # システム一括起動用 (PostgreSQLへの移行も見据えた構成)
├── Dockerfile                 # Python実行環境定義 (Pandas/Streamlit等)
├── requirements.txt           # 依存ライブラリ
├── .env.example               # 環境変数のテンプレート
├── data/                      # 永続化データ（Git管理対象外）
│   ├── assets.db              # SQLiteデータベースファイル (Runtime Store)
│   └── raw_csv/               # インポート待ちのCSV（MoneyForward等）の置き場
├── config/                    # 設定ファイル (User Interface for Params)
│   ├── settings.yaml          # システム全般設定
│   └── standard_costs.yaml    # 生活標準原価（Unit Economics）入力用ファイル
├── scripts/                   # ユーティリティスクリプト
│   └── db_init.py             # 初期DBスキーマ作成・初期マスタ(AssetClass等)投入
└── src/                       # アプリケーションソースコード
    ├── main.py                # Streamlit エントリーポイント
    ├── models/                # データモデル (Step 1)
    │   ├── __init__.py
    │   └── schema.py          # SQLAlchemy/Pydantic モデル定義
    ├── ingestion/             # データ取り込み (Step 2)
    │   ├── __init__.py
    │   ├── importer.py        # CSV正規化・DB書き込みロジック
    │   ├── config_loader.py   # YAML/Excel設定ファイルのDBロードロジック
    │   └── parsers.py         # 金融機関・サービス別CSVパーサー
    ├── core/                  # 計算・評価エンジン (Step 3)
    │   ├── __init__.py
    │   ├── valuation.py       # 時価評価・為替換算・論理残高計算
    │   ├── depreciation.py    # 耐久消費財の減価償却計算 (TCO)
    │   └── analyzer.py        # Cash Flow分析・貯蓄率・KPI算出
    ├── strategy/              # 戦略・シミュレーション (Step 4)
    │   ├── __init__.py
    │   ├── simulator.py       # モンテカルロ法等を用いた将来予測・ゴール達成確率
    │   └── auditor.py         # 購買意思決定シミュレータ (Purchase Audit)
    └── ui/                    # プレゼンテーションレイヤー
        ├── __init__.py
        ├── dashboard.py       # Streamlit 画面レイアウト
        └── components.py      # グラフ・ウィジェット等の再利用可能部品
```

## 各ディレクトリの詳細

### 1. `src/models/` (Data Architecture)
- **役割:** データベースの構造をコード（SQLAlchemy）として定義します。
- **Step 1:** ここで定義したモデルを元に、データベースを初期化します。

### 2. `src/ingestion/` (Data Pipeline)
- **役割:** 外部の「汚れた」CSVデータや設定ファイルを読み込み、クリーンな形式でDBへ投入します。
- **Step 2:** 金融機関ごとのフォーマット差異を吸収するパーサーと、`standard_costs.yaml` をDBへ同期するローダーを実装します。

### 3. `src/core/` (Business Logic)
- **役割:** 資産の時価評価や減価償却など、本システムの「知能」にあたる計算を担います。
- **Step 3:** 取得価格、市場価格、為替レート、経過日数を組み合わせた評価額算出ロジックを実装します。

### 4. `src/strategy/` (Decision Support)
- **役割:** 単なる現状把握を超え、将来予測や購買の可否判定など、「意思決定支援」を行います。
- **Step 4:** ライフイベントと連動したシミュレーションを実装します。

---

## 運用ルール
- **Data Integrity:** `data/` フォルダ内のDBファイルは、バックアップ時以外は直接触らず、必ず `src/models/` を経由して操作します。
- **Standard Cost Management:** 生活原価パラメータの変更は `config/standard_costs.yaml` を編集し、取り込みスクリプトを実行することでDBに反映させます（直接DBを触らない）。
- **Environment:** ライブラリのバージョン差異による計算ミスを防ぐため、原則として Docker コンテナ内での実行を推奨します。