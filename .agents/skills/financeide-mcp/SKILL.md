---
name: financeide-mcp
description: AssetManagement (FinanceIDE) の MCP ツールを安全に操作するための手順書。財務データの読み取り・Transaction / Item / Recurring / Registry / Plan の登録・変更を行うとき、または MCP 経由でユーザー資産データに触れるあらゆる作業の前に読む。
---

# FinanceIDE MCP Operations

FinanceIDE MCP（backend `/` FastAPI の facade）を通じてユーザーの実財務データを操作するときの規律。実データはユーザー資産であり、誤登録は資産評価を直接歪める。

ツールの一覧と入出力契約は [references/tool-catalog.md](references/tool-catalog.md) を先に読む。ツール名・allowlist は `mcp/contracts/write-tools.json` が正本。

## 0. 接続と対象 client の確認（必須・毎セッション）

1. `clients_list` で client を確認する。**書き込み前に必ず対象 client を特定**し、複数 client がある場合はユーザーに確認する。
   - 過去の運用では `client_id=1` が Default User（テスト用）、`client_id=2` がユーザー実データ。ID 決め打ちせず毎回確認する。
2. MCP の書き込みは認証ユーザーの権限で実行される。stdio は `.env` の `BACKEND_USERNAME/PASSWORD`、HTTP は OAuth ユーザー。どの client として動いているかを最初の read で確かめる。
3. 接続失敗時は backend（`http://localhost:8000`）と docker（`finance-db`, port 5434）の稼働を確認する。

## 1. 読み取りの作法

- 全体把握はまず `ai_context_summary` または `analysis_summary`。個別リソースは `ai_context_resources` → `ai_context_resource` で必要なものだけ読む。
- **財務状況の評価は `analysis_summary` + `capsules_list` を必ずセットで行う**。
  - Capsule はメイン口座残高と別管理。口座残高 ¥0 でも Capsule に予備費が入っていることがある（実際に誤読事故あり）。
  - P/L が赤字でも、給与が月途中で未登録なだけのことがある。「収支悪化」と即断せず給与登録タイミングを確認する。
- 取引の確認は `transactions_recent` / `transactions_list`（フィルタあり）。件数の多い一覧をそのまま全部読まない。

## 2. 書き込みの作法（preview → 実行 → 検証）

1. **preview を先に呼ぶ**: `transactions_preview` / `validate_transaction_payload` / `recurring_preview` / `monthly_plan_lines_preview` / `products_preview` / `transaction_batches_preview`。`ok_to_submit` と warnings を確認してから create する。
2. 取引タイプに迷ったら `help_choose_transaction_type`。典型対応:
   - クレカ購入: `CreditExpense`（from=クレカ liability, to=expense）
   - 現金/銀行支払い: `Expense`（from=asset, to=expense）
   - 口座間移動・積立: `Transfer` / 借入返済: `LiabilityPayment`
3. **Transaction の不変条件**: Transaction には必ず JournalEntry（2 行, debit=credit=amount）が伴う。MCP / API 経由なら backend が自動生成する。**DB 直 INSERT は禁止**（やむを得ず DB を触る場合は `process_transaction` を必ず通す — 詳細は `docs/agent_instruction/data_entry_agent_guide.md`）。
4. **change request モード**: AI 実行設定によっては write ツールが直接書き込まず `ai_change_requests` を作成する。その場合は preview 内容を報告し、ユーザーの approve / apply（ApprovalInbox または `ai_change_requests_approve/apply`）を待つ。勝手に approve しない。
5. 書き込み後は必ず読み直して検証する（作成 ID を `transactions_list` 等で再取得）。mutation のレスポンスだけで成功を報告しない。

## 3. Registry が正（source of truth）

- 定常収支の定義は `registry_entries` が正本。Recurring / 月次プラン行は Registry から生成される側。
- **定常的な収支を追加・変更するときは `registry_entries_create/update` を使い、生成物の recurring を直接編集しない**。registry と recurring のリンクは 1:1 を保つ。
- `recurring_create/update` を直接使ってよいのは、ユーザーが recurring 単体の操作を明示的に指示した場合のみ（その場合も backend が registry entry を自動同期する）。
- Item / 消耗品 / 耐久財のマスタは `products_*`。`budget_account_id` と `category` を一致させ、reserve 対象は `funding_capsule_id` を設定する。

## 4. Recurring（自動計上）の意味論

- `auto_post=true`: due（`next_due_date` 到来）で自動計上される対象。`false`: 手動承認用。
- `next_due_date` はシステム計算値。原則手で設定しない。
- `recurring_due` で due 一覧、`recurring_process` で 1 件計上（due 日で計上・仕訳同時作成）、`recurring_skip` で計上せず 1 期進める。
- 一括処理エンドポイント（process-due）がある場合はそちらを優先する。二重計上防止のため、同じ recurring への process 連打はしない（1 回で 1 期進む）。

## 5. 破壊的操作

- `*_delete` / `data_import_replace_current_client` / `accounts_delete` は、ユーザーの明示的な指示なしに実行しない。実行前に対象 ID と件数を提示して確認する。
- `exchange_rates_auto_update` や `capsules_process` のような一括系も、影響範囲（何件・どの期間）を先に説明する。

## 6. 完了報告フォーマット

短く、以下のみ:

- 登録/変更した ID（Transaction / Product / Registry / Recurring）
- 合計金額、支払元/費目
- change request にした場合はその ID と承認待ちである旨
- 保留した項目と理由

長い説明は不要。ユーザーは詳細を UI / DB で直接確認できる。

## 関連資料

- [references/tool-catalog.md](references/tool-catalog.md) — ツール分類と契約
- `docs/agent_instruction/data_entry_agent_guide.md` — DB 直接操作を含む登録代行の詳細手順
- `docs/agent_knowledge/asset_management_system.md` — システム構成・Capsule の罠
- `docs/agent_knowledge/agent_behavior.md` — 協働で確認された判断基準
