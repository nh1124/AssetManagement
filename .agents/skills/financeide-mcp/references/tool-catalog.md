# FinanceIDE MCP Tool Catalog

ツール名・write ツールの許可フィールドの正本は `mcp/contracts/write-tools.json`。実装は `mcp/src/tools/*.ts`。ここは選択のための地図であり、スキーマが食い違う場合は実際のツールスキーマを再確認する。

## 読み取り（安全・確認不要）

| グループ | 主なツール | 用途 |
|---|---|---|
| コンテキスト | `ai_context_summary`, `ai_context_resources`, `ai_context_resource` | 全体像の取得。最初に呼ぶ |
| 分析 | `analysis_summary`, `analysis_profit_loss`, `analysis_balance_sheet`, `analysis_variance` | KPI / P/L / BS / 予実 |
| 口座 | `accounts_list`, `accounts_net_worth` | 口座と純資産 |
| 取引 | `transactions_list`, `transactions_recent`, `transaction_batches_list/get` | 取引照会（フィルタあり） |
| 取り置き | `capsules_list`, `capsule_rules_list`, `capsule_funding_sources_list` | **財務評価時は必ず確認** |
| 自動取引 | `auto_transactions_list` | 決まった取引の設定（自動で走る取引の正本） |
| 計画 | `monthly_plan_lines_list`, `monthly_plan_summary` | 月の計画行（プランはクライアントに 1 つ）。要約の予測も月の予算（自動取引・取り置きの月額）で数える |
| ゴール | `life_scenarios_list`, `life_scenarios_simulate`, `life_events_list`, `goal_plan_check` | シナリオ・シミュレーション・イベント・計画との差 |
| レポート | `reports_monthly`, `reports_period`, `period_reviews_get`, `actions_list` | 月次/期間レビュー・行動 |
| シミュレーション | `simulation_config_get` | 試算の変動率・税率 |
| 計算機 | `calc_future_value(_multi)`, `calc_nisa_cap_usage`, `calc_dc_tax_saving`, `calc_project_all` | 副作用なし |
| その他 | `products_list`, `products_unit_economics_summary`, `exchange_rates_list`, `fx_tracked_currencies_list`, `clients_list` | マスタ類 |

## preview（副作用なし・write 前に必ず）

`transactions_preview`, `validate_transaction_payload`, `monthly_plan_lines_preview`, `products_preview`, `transaction_batches_preview`, `goal_plan_preview`, `product_reserve_plan_preview`

## 書き込み（対象 client 確認 + preview 後）

| グループ | 主なツール | 注意 |
|---|---|---|
| 取引 | `transactions_create/update/delete`, `transaction_batches_create` | JournalEntry は backend が自動生成（2 行以上、借方計 = 貸方計 = `amount`）。1 回の支払いが複数科目に分かれるときは `legs` を渡す。delete は明示指示時のみ |
| 自動取引 | `auto_transactions_create/update/delete` | **定期・一回限りの取引はここから**。有効なものは期日に必ず記帳される（記帳待ちは無い） |
| 物品 | `products_create/update/delete` | 予算での扱いに応じて `budget_account_id`（支出口座）か `funding_capsule_id`（積立先）。減価は `auto_depreciation` |
| 計画 | `monthly_plan_lines_save_batch/delete`, `budget_plans_copy_period`, `product_reserve_plan_apply` | ゴールが書いた行（source `goal`）は `goal_plan_apply` で作り直す。手編集は避ける。物品の取り置きの行は `product_reserve_plan_preview` → `product_reserve_plan_apply`（基準 saved/remaining、確保済みの引き方 recent/even、fingerprint） |
| 取り置き | `capsules_create/update/delete`, `capsule_rules_*`, `capsule_funding_sources_set` | 一括系は影響範囲を先に説明 |
| 口座 | `accounts_create/update/delete` | delete は明示指示時のみ。既定の口座は作られない |
| ゴール | `life_events_create/update/delete`（作成は `scenario_id` 必須）、`contribution_plans_create/update/delete`（積立設定）、`assumption_periods_create/update/delete`（期間ごとの前提：期間の既定の年利・インフレ）、`goal_plan_apply` | `goal_plan_apply` は `goal_plan_preview` の fingerprint を渡す。シナリオの作成・接続・前提条件は画面だけ |
| レビュー | `period_reviews_upsert`, `actions_apply/skip/process_due` | |
| 為替 | `fx_tracked_currencies_create/delete`, `exchange_rates_auto_update`, `exchange_rates_delete` | auto_update は外部取得（手入力のレートは無い） |
| データ移送 | `data_export`, `data_import_validate`, `data_import_replace_current_client` | **replace は全置換・最危険**。validate → ユーザー確認必須 |
| 設定 | `clients_update_settings`, `simulation_config_update` | client の新規作成は UI から |

## AI 承認フロー

- `ai_change_requests_create/preview/list/refresh_preview` — 変更案の作成・確認
- `ai_change_requests_approve/apply/reject` — **ユーザーの明示指示があるときのみ**
- write ツールが change request モードのとき、`*_create/update` の戻りは「書き込み結果」ではなく「承認待ち change request」。報告時に区別すること。

## 書き込み契約の要点

- write ツールの payload はフィールド allowlist 制（`mcp/contracts/write-tools.json`）。allowlist 外のフィールドは送っても無視 or エラー。
- `transactions_create` / `transactions_update` の `legs` は `[{account_id, debit|credit, memo?}]`。借方計 = 貸方計 = `amount` を満たさないと backend が拒否する。渡した場合 `from_account_id` / `to_account_id` は無視される（レグが正）。
- update 系は部分更新（送ったフィールドだけ変わる）。
- 金額は数値、日付は `YYYY-MM-DD`、期間は `YYYY-MM`、通貨コードは `JPY` など ISO。
