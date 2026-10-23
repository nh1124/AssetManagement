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
  - 取り置き（Capsule）は口座残高の内訳（お金は口座から動かない）。口座残高のうち確保額の分は用途が決まっている。取り置きを見ずに「自由に使える額」を判断しない（実際に誤読事故あり）。
  - P/L が赤字でも、給与が月途中で未登録なだけのことがある。「収支悪化」と即断せず給与登録タイミングを確認する。
- 取引の確認は `transactions_recent` / `transactions_list`（フィルタあり）。件数の多い一覧をそのまま全部読まない。

## 2. 書き込みの作法（preview → 実行 → 検証）

1. **preview を先に呼ぶ**: `transactions_preview` / `validate_transaction_payload` / `monthly_plan_lines_preview` / `products_preview` / `transaction_batches_preview`。`ok_to_submit` と warnings を確認してから create する。
2. **取引タイプという項目はもう無い**（`transactions.type` は P7-001 で削除）。科目が取引の内容を語る。
   - クレカ購入: from=クレカ liability, to=expense（現金は動かない。明細の支払いは別の取引）
   - 現金/銀行支払い: from=asset, to=expense / 収入: from=income, to=asset
   - 口座間移動・積立: asset → asset / 借入返済: from=asset, to=liability / 借入: from=liability, to=asset
   - 迷ったら `accounts_list` と `validate_transaction_payload`。科目側の指針は MCP リソース
     `asset-management://guide/accounting-rules`（`help_choose_transaction_type` は廃止）。
   - 負債が毎月締めで精算されるか（`liability_kind='card'`）、独自の返済スケジュールか（`'loan'`）は科目の属性。
3. **Transaction の不変条件**: Transaction には必ず JournalEntry が伴う。**2 行以上**で、借方合計 = 貸方合計 = `amount`。MCP / API 経由なら backend が検算する。**DB への直接の書き込みは禁止**（入力代行の手順は `docs/agents/data_entry_guide.md`）。
4. **1 回の支払いが複数科目に分かれる場合は `legs` を使う**（取引を 2 件に分けない）。立替込みの食事なら、貸方にカード 1 本、借方に 食費 と 立替科目。
   - 誰への立替かは**勘定科目で表す**（`立替 / 友人A` を asset 科目として作る）。貸している額はその科目の残高そのもので、回収は その科目 → 現金 の Transfer 1 本。
   - `amount` は支払総額のまま。各レグはその内訳で、合計が `amount` に一致しないと拒否される。
5. **change request モード**: AI 実行設定によっては write ツールが直接書き込まず `ai_change_requests` を作成する。その場合は preview 内容を報告し、ユーザーの approve / apply（ApprovalInbox または `ai_change_requests_approve/apply`）を待つ。勝手に approve しない。
6. 書き込み後は必ず読み直して検証する（作成 ID を `transactions_list` 等で再取得）。mutation のレスポンスだけで成功を報告しない。

## 3. 自動取引が正（source of truth）

- 決まった取引（定期・一回限り）の正本は自動取引（`registry_entries`、ツールは `auto_transactions_*`）。種類は収入・支出・返済・振替、
  繰り返しは一回限り／回数指定／指定なし（開始日・終了日）。月の計画行は「予算に反映する」自動取引の月額を数える側。
- **有効な自動取引は期日に必ず記帳される**（日次・サインイン時。記帳待ちや手動の計上ツールは無い）。記帳した取引は `registry_entry_id` を持つ。
  止めたいときは無効にするか終了日を入れる。次回日はシステムが進めるので手で設定しない。
- 物品（消耗品・固定資産）のマスタは `products_*`。予算での扱いに応じて `budget_account_id`（支出口座）か `funding_capsule_id`（積立先）を設定する。
  固定資産の減価は `auto_depreciation` がオンのときだけ自動で記帳される。

## 4. ゴールと計画

- シナリオ＝ライフイベント・接続・前提条件・積立設定（積立・口座振替・取り崩しのレコード）・期間ごとの前提。作成・複製・接続・前提条件も MCP でできる（`life_scenarios_*`・`life_event_links_*`・`life_event_conditions_*`）。
- 計画への反映は `plan_reflection_*`：設定（基準・確保済みの引き方・遅れの取り返し・物品の取り置き・自動反映）を `plan_reflection_get` で読み、`plan_reflection_preview` で変わる行をユーザーに見せてから `plan_reflection_settings_update` か `plan_reflection_run`。今月から 12 か月を作り直し、過去の月とユーザーのレコードは変えない。自動反映がオンなら月の初めと設定の変更で自動で走る。
- 計画との差は `goal_plan_check`（口座ごとに積立設定の月額と計画の配分）。

## 5. 破壊的操作

- `*_delete` / `data_import_replace_current_client` / `accounts_delete` は、ユーザーの明示的な指示なしに実行しない。実行前に対象 ID と件数を提示して確認する。
- `exchange_rates_auto_update`・`plan_reflection_run`・`reconcile_adjust` のような一括系も、影響範囲（何件・どの期間）を先に説明する。
- アカウント操作（ログイン・登録・パスワード・MFA）と AI 自身の権限設定（AI ポリシー・書込方式）は MCP に無い。ユーザーに画面で行ってもらう。

## 6. 完了報告フォーマット

短く、以下のみ:

- 登録/変更した ID（Transaction / Product / 自動取引 / ライフイベント）
- 合計金額、支払元/費目
- change request にした場合はその ID と承認待ちである旨
- 保留した項目と理由

長い説明は不要。ユーザーは詳細を UI / DB で直接確認できる。

## 関連資料

- [references/tool-catalog.md](references/tool-catalog.md) — ツール分類と契約
- `docs/agents/data_entry_guide.md` — 取引・物品の登録代行の手順（物品の項目と予算での扱い）
- `docs/agents/asset_management_system.md` — システム構成・取り置き（Capsule）の読み方
- `docs/specs/system_overview.md` — システムの今の全体像
- `docs/agents/agent_behavior.md` — 協働で確認された判断基準
