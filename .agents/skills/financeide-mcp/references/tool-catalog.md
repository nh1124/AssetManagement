# FinanceIDE MCP Tool Catalog

ツール名・write ツールの許可フィールドの正本は `mcp/contracts/write-tools.json`。実装は `mcp/src/tools/*.ts`。ここは選択のための地図であり、スキーマが食い違う場合は実際のツールスキーマを再確認する。

## 読み取り（安全・確認不要）

| グループ | 主なツール | 用途 |
|---|---|---|
| コンテキスト | `ai_context_summary`, `ai_context_resources`, `ai_context_resource` | 全体像の取得。最初に呼ぶ |
| 分析 | `analysis_summary`, `analysis_profit_loss`, `analysis_balance_sheet`, `analysis_variance` | KPI / P/L / BS / 予実 |
| 口座 | `accounts_list`, `accounts_net_worth` | 口座と純資産 |
| 取引 | `transactions_list`, `transactions_recent` | 取引照会（フィルタあり） |
| Capsule | `capsules_list`, `capsule_holdings_list`, `capsule_rules_list` | **財務評価時は必ず確認** |
| Registry | `registry_entries_list/get` | 定常収支の正本 |
| Recurring | `recurring_list`, `recurring_due` | 定義と due 一覧 |
| プラン | `budget_plans_list`, `monthly_plan_lines_list`, `monthly_plan_summary` | 予算プラン |
| レポート | `reports_monthly`, `reports_period`, `monthly_reviews_get`, `period_reviews_get` | 月次/期間レビュー |
| 戦略 | `strategy_dashboard`, `roadmap_projection`, `roadmap_milestones_list` | 戦略・ロードマップ |
| シミュレーション | `simulation_config_get`, `simulation_scenarios_list/compare`, `simulation_monte_carlo` | 将来予測 |
| 計算機 | `calc_future_value(_multi)`, `calc_nisa_cap_usage`, `calc_dc_tax_saving`, `calc_project_all` | 副作用なし |
| その他 | `products_list`, `life_events_list/get`, `exchange_rates_list`, `quick_templates_list`, `clients_list` | マスタ類 |

## preview（副作用なし・write 前に必ず）

`transactions_preview`, `validate_transaction_payload`, `recurring_preview`, `monthly_plan_lines_preview`, `products_preview`, `transaction_batches_preview`, `roadmap_milestones_preview_from_simulation`, `help_choose_transaction_type`

## 書き込み（対象 client 確認 + preview 後）

| グループ | 主なツール | 注意 |
|---|---|---|
| 取引 | `transactions_create/update/delete`, `transaction_batches_create` | JournalEntry は backend が自動生成。delete は明示指示時のみ |
| Registry | `registry_entries_create/update/delete` | **定常収支はここから**。recurring が自動同期される |
| Recurring | `recurring_create/update`, `recurring_process`, `recurring_skip`, `recurring_process_due` | 直接操作は明示指示時のみ。process は 1 回 = 1 期。一括は `recurring_process_due`（auto_post 対象を catch-up 込みで計上） |
| Item | `products_create/update/delete` | `budget_account_id` と `category` を一致させる |
| プラン | `budget_plans_create/update/copy_*`, `monthly_plan_lines_save_batch/delete` | 生成行（source_kind != manual）の手編集は避ける |
| Capsule | `capsules_create/update`, `capsule_rules_*`, `capsule_holdings_*` | 一括系は影響範囲を先に説明（`capsules_process` は deprecated のため削除済み） |
| 口座 | `accounts_create/update/delete`, `accounts_seed_defaults` | delete は明示指示時のみ |
| 目標 | `life_events_create/update/delete`, `roadmap_milestones_*` | |
| レビュー | `monthly_reviews_upsert`, `period_reviews_upsert`, `actions_apply/skip/process_due` | actions は review 由来の提案適用 |
| 為替 | `exchange_rates_create/update/delete/auto_update` | auto_update は外部取得 |
| データ移送 | `data_export`, `data_import_validate`, `data_import_replace_current_client` | **replace は全置換・最危険**。validate → ユーザー確認必須 |
| 設定 | `clients_update_settings`, `clients_update_gemini_key` | client の新規作成は UI から（`clients_create` ツールは廃止済み） |

## AI 承認フロー

- `ai_change_requests_create/preview/list/refresh_preview` — 変更案の作成・確認
- `ai_change_requests_approve/apply/reject` — **ユーザーの明示指示があるときのみ**
- write ツールが change request モードのとき、`*_create/update` の戻りは「書き込み結果」ではなく「承認待ち change request」。報告時に区別すること。

## 書き込み契約の要点

- write ツールの payload はフィールド allowlist 制（`mcp/contracts/write-tools.json`）。allowlist 外のフィールドは送っても無視 or エラー。
- update 系は部分更新（送ったフィールドだけ変わる）。
- 金額は数値、日付は `YYYY-MM-DD`、期間は `YYYY-MM`、通貨コードは `JPY` など ISO。
