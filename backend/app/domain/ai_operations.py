"""Every operation the AI can perform through MCP, in one list (owner 2026-10-24, C8/C9).

The gateway (routers/ai_operation_audit) matches each MCP request to one of these and
lets it through, sends it to a change request, or refuses it by the person's setting
for that operation; the audit log names the operation; the AI screen lists them all,
grouped by section. One row is one operation the backend can tell apart, with the MCP
tools that use it: a tool that only computes (calc_*) has no row.

`default` is what an operation does with no setting saved. It reproduces the
behaviour before WP36: writes ran directly, except the ones that post to the ledger,
which needed the transactions/create permission (the AI got 403 without it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

AiMode = Literal["allow", "approval", "deny"]
AiKind = Literal["read", "write"]
AiRisk = Literal["low", "medium", "high"]
MODES: tuple[AiMode, ...] = ("allow", "approval", "deny")


@dataclass(frozen=True)
class AiSection:
    key: str
    ja: str
    en: str


@dataclass(frozen=True)
class AiOperation:
    key: str
    section: str
    kind: AiKind
    ja: str
    en: str
    risk: AiRisk
    routes: tuple[str, ...]
    tools: tuple[str, ...]
    # A change request can carry it (ai_change_request_workflow.SUPPORTED_OPERATIONS).
    approval: bool = False
    # It posts journal entries; before WP36 these shared the transactions/create gate.
    ledger: bool = False
    # Writes refused in change-request mode; the change-request operations themselves are not.
    by_write_mode: bool = True

    @property
    def resource(self) -> str:
        return self.key.rsplit(".", 1)[0]

    @property
    def action(self) -> str:
        return self.key.rsplit(".", 1)[1]

    @property
    def modes(self) -> tuple[AiMode, ...]:
        if self.kind == "read" or not self.approval:
            return ("allow", "deny")
        return MODES

    @property
    def default(self) -> AiMode:
        if not self.ledger:
            return "allow"
        return "approval" if self.approval else "deny"


SECTIONS: tuple[AiSection, ...] = (
    AiSection("ledger", "取引と仕訳", "Transactions and entries"),
    AiSection("plan", "計画", "Plan"),
    AiSection("automatic", "自動取引", "Automatic transactions"),
    AiSection("accounts", "口座と照合", "Accounts and reconciliation"),
    AiSection("earmarks", "取り置き", "Earmarks"),
    AiSection("products", "物品と減価", "Items and depreciation"),
    AiSection("goals", "ゴール・シナリオ・ライフイベント", "Goals, scenarios and life events"),
    AiSection("fx", "為替", "Exchange rates"),
    AiSection("reports", "集計・レポート", "Analysis and reports"),
    AiSection("data", "データと設定", "Data and settings"),
    AiSection("notices", "通知・振り返り", "Notifications and reviews"),
    AiSection("ai", "AI 連携", "AI"),
)


def _op(key, section, kind, ja, en, risk, routes, tools, **flags) -> AiOperation:
    return AiOperation(key, section, kind, ja, en, risk, tuple(routes), tuple(tools), **flags)


OPERATIONS: tuple[AiOperation, ...] = (
    # ─── 取引と仕訳 ───
    _op("transactions.read", "ledger", "read", "取引・候補・一括登録を読み取る", "Read transactions, pending recordings and batches", "low",
        ["GET /transactions/**", "GET /transaction-batches/**"],
        ["transactions_list", "transactions_recent", "transactions_get", "transaction_proposals_list",
         "transaction_batches_list", "transaction_batches_get", "transactions_preview", "transaction_batches_preview",
         "validate_transaction_payload"]),
    _op("transactions.create", "ledger", "write", "取引を記録する", "Record a transaction", "medium",
        ["POST /transactions"], ["transactions_create"], approval=True, ledger=True),
    _op("transactions.update", "ledger", "write", "取引を変更する", "Change a transaction", "medium",
        ["PUT /transactions/{id}"], ["transactions_update"], ledger=True),
    _op("transactions.delete", "ledger", "write", "取引を削除する", "Delete a transaction", "high",
        ["DELETE /transactions/{id}"], ["transactions_delete"], ledger=True),
    _op("transaction_batches.create", "ledger", "write", "取引をまとめて記録する", "Record transactions in a batch", "medium",
        ["POST /transaction-batches"], ["transaction_batches_create"], ledger=True),
    # ─── 計画 ───
    _op("plan.read", "plan", "read", "計画を読み取る", "Read the plan", "low",
        ["GET /budget-plans/**", "GET /plan/**", "POST /plan/reflection/preview"],
        ["monthly_plan_summary", "monthly_plan_lines_list", "monthly_plan_lines_preview", "plan_account_month",
         "plan_reflection_get", "plan_reflection_preview"]),
    _op("plan_lines.create", "plan", "write", "計画の行を作る", "Create plan lines", "medium",
        ["POST /budget-plans/lines"], ["monthly_plan_lines_save_batch"]),
    _op("plan_lines.update", "plan", "write", "計画の行を変更する", "Change plan lines", "medium",
        ["PUT /budget-plans/lines/batch"], ["monthly_plan_lines_save_batch"], approval=True),
    _op("plan_lines.delete", "plan", "write", "計画の行を削除する", "Delete a plan line", "high",
        ["DELETE /budget-plans/lines/{id}"], ["monthly_plan_lines_delete"]),
    _op("budget_plans.copy_period", "plan", "write", "月の計画をコピーする", "Copy a month's plan", "medium",
        ["POST /budget-plans/copy-period"], ["budget_plans_copy_period"]),
    _op("plan_records.create", "plan", "write", "計画のレコードを追加する", "Add a plan record", "medium",
        ["POST /plan/records"], ["plan_records_add"]),
    _op("plan_records.update", "plan", "write", "計画のレコードを変更する", "Change a plan record", "medium",
        ["PUT /plan/records/{id}"], ["plan_records_update"]),
    _op("plan_records.delete", "plan", "write", "計画のレコードを削除する", "Delete a plan record", "high",
        ["DELETE /plan/records/{id}"], ["plan_records_delete"]),
    _op("plan_reflection.settings", "plan", "write", "計画への反映の設定を変える", "Change the plan reflection settings", "medium",
        ["PUT /plan/reflection/settings"], ["plan_reflection_settings_update"]),
    _op("plan_reflection.run", "plan", "write", "計画への反映を実行する", "Run the plan reflection", "medium",
        ["POST /plan/reflection/run"], ["plan_reflection_run"]),
    # ─── 自動取引 ───
    _op("auto_transactions.read", "automatic", "read", "自動取引と今月の予定を読み取る", "Read automatic transactions and this month's schedule", "low",
        ["GET /auto-transactions/**", "GET /automatic-recordings/**"], ["auto_transactions_list", "automatic_scheduled"]),
    _op("auto_transactions.create", "automatic", "write", "自動取引を作る", "Create an automatic transaction", "medium",
        ["POST /auto-transactions"], ["auto_transactions_create"], approval=True),
    _op("auto_transactions.update", "automatic", "write", "自動取引を変更する", "Change an automatic transaction", "medium",
        ["PUT /auto-transactions/{id}"], ["auto_transactions_update"], approval=True),
    _op("auto_transactions.delete", "automatic", "write", "自動取引を削除する", "Delete an automatic transaction", "high",
        ["DELETE /auto-transactions/{id}"], ["auto_transactions_delete"]),
    # ─── 口座と照合 ───
    _op("accounts.read", "accounts", "read", "口座と照合を読み取る", "Read accounts and reconciliation", "low",
        ["GET /accounts/**", "GET /analysis/reconcile/**"], ["accounts_list", "accounts_net_worth", "reconcile_account"]),
    _op("accounts.create", "accounts", "write", "口座・勘定科目を作る", "Create an account", "medium",
        ["POST /accounts"], ["accounts_create"]),
    _op("accounts.update", "accounts", "write", "口座・勘定科目を変更する", "Change an account", "medium",
        ["PUT /accounts/{id}"], ["accounts_update"]),
    _op("accounts.delete", "accounts", "write", "口座・勘定科目を削除する", "Delete an account", "high",
        ["DELETE /accounts/{id}"], ["accounts_delete"]),
    _op("accounts.reconcile_adjust", "accounts", "write", "照合の差額を記帳する", "Post a reconciliation adjustment", "high",
        ["POST /analysis/reconcile/{id}/adjust"], ["reconcile_adjust"], ledger=True),
    # ─── 取り置き ───
    _op("capsules.read", "earmarks", "read", "取り置き・規則・資金元・使用記録を読み取る", "Read earmarks, rules, funding sources and uses", "low",
        ["GET /capsules/**"], ["capsules_list", "capsule_rules_list", "capsule_funding_sources_list", "capsule_drawdowns_list"]),
    _op("capsules.create", "earmarks", "write", "取り置きを作る", "Create an earmark", "medium",
        ["POST /capsules"], ["capsules_create"]),
    _op("capsules.update", "earmarks", "write", "取り置きを変更する", "Change an earmark", "medium",
        ["PUT /capsules/{id}"], ["capsules_update"]),
    _op("capsules.delete", "earmarks", "write", "取り置きを削除する", "Delete an earmark", "high",
        ["DELETE /capsules/{id}"], ["capsules_delete"]),
    _op("capsules.funding_sources", "earmarks", "write", "取り置きの資金元を設定する", "Set an earmark's funding sources", "medium",
        ["PUT /capsules/{id}/funding-sources"], ["capsule_funding_sources_set"]),
    _op("capsule_rules.create", "earmarks", "write", "取り置きの規則を作る", "Create an earmark rule", "medium",
        ["POST /capsules/rules"], ["capsule_rules_create"]),
    _op("capsule_rules.update", "earmarks", "write", "取り置きの規則を変更する", "Change an earmark rule", "medium",
        ["PUT /capsules/rules/{id}"], ["capsule_rules_update"]),
    _op("capsule_rules.delete", "earmarks", "write", "取り置きの規則を削除する", "Delete an earmark rule", "high",
        ["DELETE /capsules/rules/{id}"], ["capsule_rules_delete"]),
    _op("capsules.contribute", "earmarks", "write", "取り置きに確保する", "Set money aside in an earmark", "medium",
        ["POST /capsules/{id}/contribute"], ["capsules_contribute"], ledger=True),
    _op("capsules.drawdown", "earmarks", "write", "取り置きから使う", "Use money from an earmark", "medium",
        ["POST /capsules/{id}/drawdown"], ["capsules_drawdown"], ledger=True),
    _op("capsules.account_claim", "earmarks", "write", "取り置きの確保額を調整する", "Adjust what an earmark holds", "medium",
        ["POST /capsules/{id}/account-claim"], ["capsules_set_account_claim"], ledger=True),
    # ─── 物品と減価 ───
    _op("products.read", "products", "read", "物品と減価を読み取る", "Read items and depreciation", "low",
        ["GET /products/**", "GET /depreciations/**"],
        ["products_list", "products_unit_economics_summary", "products_preview", "depreciation_preview"]),
    _op("products.create", "products", "write", "物品を登録する", "Register an item", "medium",
        ["POST /products"], ["products_create"]),
    _op("products.update", "products", "write", "物品を変更する", "Change an item", "medium",
        ["PATCH /products/{id}"], ["products_update"]),
    _op("products.delete", "products", "write", "物品を削除する", "Delete an item", "high",
        ["DELETE /products/{id}"], ["products_delete"]),
    _op("depreciations.record", "products", "write", "減価を記録する", "Record a depreciation", "medium",
        ["POST /depreciations"], ["depreciation_record"], ledger=True),
    _op("depreciations.amend", "products", "write", "減価を修正する", "Amend a depreciation", "medium",
        ["PUT /depreciations/{id}"], ["depreciation_amend"], ledger=True),
    # ─── ゴール・シナリオ・ライフイベント ───
    _op("goals.read", "goals", "read", "ゴール・シナリオ・イベント・世帯を読み取る", "Read goals, scenarios, events and the household", "low",
        ["GET /life-events/**", "GET /life-scenarios/**", "GET /household-members/**", "GET /goal-budget/**"],
        ["life_scenarios_list", "life_scenarios_simulate", "life_scenarios_goal_preview", "goal_plan_check",
         "life_events_list", "life_event_links_list", "life_event_conditions_list", "household_members_list"]),
    _op("life_scenarios.create", "goals", "write", "シナリオを作る", "Create a scenario", "medium",
        ["POST /life-scenarios"], ["life_scenarios_create"]),
    _op("life_scenarios.update", "goals", "write", "シナリオを変更する", "Change a scenario", "medium",
        ["PUT /life-scenarios/{id}"], ["life_scenarios_update"]),
    _op("life_scenarios.duplicate", "goals", "write", "シナリオを複製する", "Duplicate a scenario", "medium",
        ["POST /life-scenarios/{id}/duplicate"], ["life_scenarios_duplicate"]),
    _op("life_scenarios.delete", "goals", "write", "シナリオを削除する", "Delete a scenario", "high",
        ["DELETE /life-scenarios/{id}"], ["life_scenarios_delete"]),
    _op("life_scenarios.make_goal", "goals", "write", "シナリオをゴールにする", "Make a scenario the goal", "medium",
        ["POST /life-scenarios/{id}/goal"], ["life_scenarios_make_goal"]),
    _op("life_events.create", "goals", "write", "ライフイベントを作る", "Create a life event", "medium",
        ["POST /life-events"], ["life_events_create"]),
    _op("life_events.update", "goals", "write", "ライフイベントを変更する", "Change a life event", "medium",
        ["PUT /life-events/{id}"], ["life_events_update"]),
    _op("life_events.delete", "goals", "write", "ライフイベントを削除する", "Delete a life event", "high",
        ["DELETE /life-events/{id}"], ["life_events_delete"]),
    _op("life_event_links.create", "goals", "write", "イベントをつなぐ", "Link two life events", "medium",
        ["POST /life-events/links"], ["life_event_links_create"]),
    _op("life_event_links.delete", "goals", "write", "イベントのつながりを削除する", "Delete a life event link", "high",
        ["DELETE /life-events/links/{id}"], ["life_event_links_delete"]),
    _op("life_event_conditions.create", "goals", "write", "前提条件を追加する", "Add a precondition", "medium",
        ["POST /life-events/{id}/conditions"], ["life_event_conditions_create"]),
    _op("life_event_conditions.update", "goals", "write", "前提条件を変更する", "Change a precondition", "medium",
        ["PUT /life-events/{id}/conditions/{id}"], ["life_event_conditions_update"]),
    _op("life_event_conditions.delete", "goals", "write", "前提条件を削除する", "Delete a precondition", "high",
        ["DELETE /life-events/{id}/conditions/{id}"], ["life_event_conditions_delete"]),
    _op("contribution_plans.create", "goals", "write", "積立設定を追加する", "Add a contribution plan", "medium",
        ["POST /life-scenarios/{id}/contribution-plans"], ["contribution_plans_create"]),
    _op("contribution_plans.update", "goals", "write", "積立設定を変更する", "Change a contribution plan", "medium",
        ["PUT /life-scenarios/contribution-plans/{id}"], ["contribution_plans_update"]),
    _op("contribution_plans.delete", "goals", "write", "積立設定を削除する", "Delete a contribution plan", "high",
        ["DELETE /life-scenarios/contribution-plans/{id}"], ["contribution_plans_delete"]),
    _op("assumption_periods.create", "goals", "write", "期間ごとの前提を追加する", "Add an assumption period", "medium",
        ["POST /life-scenarios/{id}/assumption-periods"], ["assumption_periods_create"]),
    _op("assumption_periods.update", "goals", "write", "期間ごとの前提を変更する", "Change an assumption period", "medium",
        ["PUT /life-scenarios/assumption-periods/{id}"], ["assumption_periods_update"]),
    _op("assumption_periods.delete", "goals", "write", "期間ごとの前提を削除する", "Delete an assumption period", "high",
        ["DELETE /life-scenarios/assumption-periods/{id}"], ["assumption_periods_delete"]),
    _op("household_members.create", "goals", "write", "世帯員を追加する", "Add a household member", "medium",
        ["POST /household-members"], ["household_members_create"]),
    _op("household_members.update", "goals", "write", "世帯員を変更する", "Change a household member", "medium",
        ["PUT /household-members/{id}"], ["household_members_update"]),
    _op("household_members.delete", "goals", "write", "世帯員を削除する", "Delete a household member", "high",
        ["DELETE /household-members/{id}"], ["household_members_delete"]),
    # ─── 為替 ───
    _op("exchange_rates.read", "fx", "read", "為替レートと追跡する通貨を読み取る", "Read exchange rates and tracked currencies", "low",
        ["GET /exchange-rates/**"], ["exchange_rates_list", "fx_tracked_currencies_list"]),
    _op("exchange_rates.auto_update", "fx", "write", "為替レートを取得する", "Fetch exchange rates", "medium",
        ["POST /exchange-rates/auto-update"], ["exchange_rates_auto_update"]),
    _op("exchange_rates.delete", "fx", "write", "為替レートを削除する", "Delete an exchange rate", "high",
        ["DELETE /exchange-rates/{id}"], ["exchange_rates_delete"]),
    _op("fx_tracked.create", "fx", "write", "追跡する通貨を追加する", "Track a currency", "medium",
        ["POST /exchange-rates/tracked"], ["fx_tracked_currencies_create"]),
    _op("fx_tracked.delete", "fx", "write", "追跡する通貨を外す", "Stop tracking a currency", "high",
        ["DELETE /exchange-rates/tracked/{id}"], ["fx_tracked_currencies_delete"]),
    # ─── 集計・レポート ───
    _op("analysis.read", "reports", "read", "集計とレポートを読み取る", "Read analysis and reports", "low",
        ["GET /analysis/**", "GET /reports/**"],
        ["analysis_summary", "analysis_balance_sheet", "analysis_profit_loss", "analysis_variance", "analysis_account_flows",
         "analysis_account_transactions", "analysis_net_worth_history", "reports_monthly", "reports_period"]),
    # ─── データと設定 ───
    _op("data.read", "data", "read", "データの確認と取り込みの検証", "Check data health and validate an import", "low",
        ["GET /data/health", "POST /data/import/validate"], ["data_health_check", "data_import_validate"]),
    _op("data.export", "data", "read", "データを書き出す", "Export the data", "high",
        ["GET /data/export"], ["data_export"]),
    _op("data.import", "data", "write", "データを取り込んで置き換える", "Import and replace the data", "high",
        ["POST /data/import"], ["data_import_replace_current_client"]),
    _op("settings.read", "data", "read", "設定と試算の設定を読み取る", "Read the settings and simulation settings", "low",
        ["GET /clients/**", "GET /simulation/**"], ["clients_list", "simulation_config_get"]),
    _op("settings.update", "data", "write", "設定を変える", "Change the settings", "medium",
        ["PUT /clients/{id}/settings"], ["clients_update_settings"]),
    _op("simulation.update", "data", "write", "試算の設定を変える", "Change the simulation settings", "medium",
        ["PUT /simulation/config"], ["simulation_config_update"]),
    # ─── 通知・振り返り ───
    _op("notifications.read", "notices", "read", "通知を読み取る", "Read notifications", "low",
        ["GET /notifications/**"], ["notifications_list"]),
    _op("notifications.decide", "notices", "write", "通知を後で確認・見送りにする", "Snooze or dismiss a notification", "low",
        ["POST /notifications/{id}/decision"], ["notifications_decide"]),
    _op("period_reviews.read", "notices", "read", "振り返りを読み取る", "Read period reviews", "low",
        ["GET /period-reviews/**"], ["period_reviews_get"]),
    _op("period_reviews.upsert", "notices", "write", "振り返りを書く", "Write a period review", "medium",
        ["PUT /period-reviews"], ["period_reviews_upsert"]),
    # ─── AI 連携 ───
    _op("ai_context.read", "ai", "read", "AI 向けの文脈を読み取る", "Read the AI context", "low",
        ["GET /ai/context/**"], ["ai_context_resources", "ai_context_summary", "ai_context_resource"]),
    _op("change_requests.read", "ai", "read", "承認リクエストを読み取る・試す", "Read and try change requests", "low",
        ["GET /ai/change-requests/**", "POST /ai/change-requests/preview"], ["ai_change_requests_list", "ai_change_requests_preview"]),
    _op("change_requests.create", "ai", "write", "承認リクエストを作る・作り直す", "Create or rebuild a change request", "low",
        ["POST /ai/change-requests", "POST /ai/change-requests/{id}/refresh-preview"],
        ["ai_change_requests_create", "ai_change_requests_refresh_preview"], by_write_mode=False),
    _op("change_requests.apply", "ai", "write", "承認されたリクエストを適用する", "Apply an approved change request", "medium",
        ["POST /ai/change-requests/{id}/apply"], ["ai_change_requests_apply"], by_write_mode=False),
)

# MCP tools that only compute: they call nothing in the backend, so no permission applies.
LOCAL_TOOLS: tuple[str, ...] = (
    "calc_future_value", "calc_future_value_multi", "calc_project_all", "calc_dc_tax_saving", "calc_nisa_cap_usage",
)

# What the MCP server itself asks before a write; not something the AI does.
PLUMBING: tuple[str, ...] = ("GET /ai/execution-settings",)

BY_KEY: dict[str, AiOperation] = {operation.key: operation for operation in OPERATIONS}


@dataclass(frozen=True)
class _Route:
    method: str
    pattern: re.Pattern
    literals: int
    prefix: bool
    operation: AiOperation | None


def _normalize(path: str) -> str:
    return "/" + path.strip("/")


def _compile(spec: str, operation: AiOperation | None) -> _Route:
    method, path = spec.split(" ", 1)
    prefix = path.endswith("/**")
    segments = [segment for segment in path.removesuffix("/**").strip("/").split("/") if segment]
    parts = ["[^/]+" if segment.startswith("{") else re.escape(segment) for segment in segments]
    body = "/" + "/".join(parts)
    pattern = re.compile(f"^{body}(?:/.*)?$" if prefix else f"^{body}$")
    literals = sum(1 for segment in segments if not segment.startswith("{"))
    return _Route(method, pattern, literals, prefix, operation)


_ROUTES: tuple[_Route, ...] = tuple(
    _compile(spec, operation) for operation in OPERATIONS for spec in operation.routes
) + tuple(_compile(spec, None) for spec in PLUMBING)


def match(method: str, path: str) -> tuple[bool, AiOperation | None]:
    """(known, operation) for one request. Plumbing is known with no operation.

    The most specific route wins: an exact route over a prefix (`/**`), then the one
    with more literal segments, so GET /analysis/reconcile/3 is a reconciliation read,
    not an analysis read.
    """
    path = _normalize(path)
    candidates = [route for route in _ROUTES if route.method == method.upper() and route.pattern.match(path)]
    if not candidates:
        return False, None
    best = max(candidates, key=lambda route: (not route.prefix, route.literals))
    return True, best.operation
