from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .money_storage import to_minor, money_client_currency, rule_amount_fields

from .. import models
from ..domain.errors import Invalid
from ..domain.money import Money
from ..domain.journal import Leg, coerce_leg, validate_legs
from ..domain.transfer import (
    EXPORT_VERSION,
    build_manifest,
    row_fields,
    data_counts,
    parse_date,
    parse_datetime,
    validate_import_payload,
    migrate_account_fields,
    migrate_event_fundings,
    migrate_event_withdrawals,
    migrate_plan_records,
    migrate_goal_fields,
    migrate_goal_v2,
)
from .data_health_service import check_data_health
from .budget_lines import assign_plan_line_identity
from .cache_service import invalidate_client
from ..domain.automatic_migration import migrate_automatic_data
from copy import deepcopy
from .life_scenario_scope import get_goal
from .life_scenario_service import seed_legacy_goal, copy_graph



def _int_or_none(value):
    return int(value) if value not in (None, "") else None

def _db_revision(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


# A backup reads the schema as a whole; feature accessors would make their
# public interfaces depend on the backup format.
def export_client(db: Session, client: models.Client) -> dict:
    tx_ids = [
        row[0]
        for row in db.query(models.Transaction.id)
        .filter(models.Transaction.client_id == client.id)
        .all()
    ]

    exported_at = datetime.utcnow().isoformat()
    data = {
            "accounts": [
                row_fields(
                    account,
                    [
                        "id",
                        "name",
                        "account_type",
                        "liability_closing_day",
                        "liability_payment_day",
                        "liability_payment_month_offset",
                        "liability_payment_policy",
                        "liability_minimum_payment",
                        "liability_fixed_payment_amount",
                        "liability_installment_months",
                        "liability_revolving_rate",
                        "is_active",
                    ],
                )
                for account in db.query(models.Account)
                .filter(models.Account.client_id == client.id)
                .order_by(models.Account.id)
                .all()
            ],
            "products": [
                row_fields(
                    product,
                    [
                        "id",
                        "name",
                        "category",
                        "location",
                        "last_unit_price",
                        "units_per_purchase",
                        "frequency_days",
                        "last_purchase_date",
                        "is_asset",
                        "lifespan_months",
                        "budget_account_id",
                        "funding_capsule_id",
                        "budget_treatment",
                        "purchase_price",
                        "purchase_date",
                        "auto_depreciation",
                        "depreciation_method",
                        "depreciation_annual_rate",
                        "depreciation_interval",
                        "depreciation_start_date",
                        "depreciation_expense_account_id",
                        "depreciation_asset_account_id",
                    ],
                )
                for product in db.query(models.Product)
                .filter(models.Product.client_id == client.id)
                .order_by(models.Product.id)
                .all()
            ],
            "product_depreciations": [
                row_fields(row, ["id", "product_id", "period", "transaction_id",
                                 "amount_minor", "created_at"])
                for row in db.query(models.ProductDepreciation)
                .filter(models.ProductDepreciation.client_id == client.id)
                .order_by(models.ProductDepreciation.product_id, models.ProductDepreciation.period)
                .all()
            ],
            "simulation_configs": [
                row_fields(
                    config,
                    [
                        "id",
                        "user_id",
                        "annual_return",
                        "tax_rate",
                        "is_nisa",
                        "volatility",
                        "inflation_rate",
                        "horizon_years",
                    ],
                )
                for config in db.query(models.SimulationConfig)
                .filter(models.SimulationConfig.client_id == client.id)
                .order_by(models.SimulationConfig.id)
                .all()
            ],
            "registry_entries": [
                row_fields(item, ["id", "name", "kind", "amount", "currency", "source_account_id", "destination_account_id",
                                  "budget_account_id", "repeat_mode", "frequency", "frequency_days", "day_of_month", "month_of_year",
                                  "start_date", "end_date", "repeat_count", "next_due_date", "budget_active", "is_active", "records_transactions", "note",
                                  "created_at", "updated_at"])
                for item in db.query(models.RegistryEntry).filter(models.RegistryEntry.client_id == client.id).order_by(models.RegistryEntry.id).all()
            ],
            "transaction_batches": [
                row_fields(
                    item,
                    [
                        "id",
                        "label",
                        "source",
                        "input_payload",
                        "created_at",
                    ],
                )
                for item in db.query(models.TransactionBatch)
                .filter(models.TransactionBatch.client_id == client.id)
                .order_by(models.TransactionBatch.id)
                .all()
            ],
            "life_events": [
                row_fields(
                    event,
                    [
                        "id",
                        "scenario_id",
                        "lineage",
                        "name",
                        "target_date",
                        "target_amount",
                        "priority",
                        "note",
                        "condition_mode",
                        "direction",
                        "interest_rate",
                        "borrowing_event_id",
                        "repeat_count",
                        "created_at",
                    ],
                )
                for event in db.query(models.LifeEvent)
                .filter(models.LifeEvent.client_id == client.id)
                .order_by(models.LifeEvent.id)
                .all()
            ],
            "life_event_links": [
                row_fields(link, ["id", "from_event_id", "to_event_id", "kind", "offset_months", "note", "created_at"])
                for link in db.query(models.LifeEventLink)
                .filter(models.LifeEventLink.client_id == client.id)
                .order_by(models.LifeEventLink.id).all()
            ],
            "life_scenarios": [
                row_fields(row, ["id", "name", "annual_return", "inflation", "horizon_years", "is_goal", "created_at", "updated_at"])
                for row in db.query(models.LifeScenario).filter_by(client_id=client.id).order_by(models.LifeScenario.id).all()
            ],
            "scenario_contribution_plans": [
                row_fields(row, ["id", "scenario_id", "kind", "account_id", "to_account_id", "start_period", "amount_minor", "interval_months",
                                 "repeat_count", "end_period", "on_shortage", "annual_return", "note", "life_event_id", "created_at"])
                for row in db.query(models.ScenarioContributionPlan).join(models.LifeScenario, models.LifeScenario.id == models.ScenarioContributionPlan.scenario_id)
                .filter(models.LifeScenario.client_id == client.id).order_by(models.ScenarioContributionPlan.id).all()
            ],
            "scenario_assumption_periods": [
                row_fields(row, ["id", "scenario_id", "start_period", "end_period", "annual_return", "inflation", "note", "created_at"])
                for row in db.query(models.ScenarioAssumptionPeriod).join(models.LifeScenario, models.LifeScenario.id == models.ScenarioAssumptionPeriod.scenario_id)
                .filter(models.LifeScenario.client_id == client.id).order_by(models.ScenarioAssumptionPeriod.id).all()
            ],
            "household_members": [
                row_fields(row, ["id", "name", "relation", "birth_date", "created_at"])
                for row in db.query(models.HouseholdMember).filter_by(client_id=client.id).order_by(models.HouseholdMember.id).all()
            ],
            "life_event_conditions": [
                row_fields(row, ["id", "life_event_id", "metric", "comparator", "threshold_minor", "threshold_number", "threshold_date", "reference_id", "note", "created_at"])
                for row in db.query(models.LifeEventCondition).filter_by(client_id=client.id).order_by(models.LifeEventCondition.id).all()
            ],
            "transactions": [
                row_fields(
                    transaction,
                    [
                        "id",
                        "date",
                        "description",
                        "amount",
                        "currency",
                        "batch_id",
                        "registry_entry_id",
                        "created_at",
                    ],
                )
                for transaction in db.query(models.Transaction)
                .filter(models.Transaction.client_id == client.id)
                .order_by(models.Transaction.id)
                .all()
            ],
            "journal_entries": [
                row_fields(entry, ["id", "transaction_id", "account_id", "capsule_id", "debit", "credit", "memo", "sort_order"])
                for entry in db.query(models.JournalEntry)
                .filter(models.JournalEntry.transaction_id.in_(tx_ids or [-1]))
                .order_by(models.JournalEntry.id)
                .all()
            ],
            "budget_plans": [
                row_fields(
                    plan,
                    [
                        "id",
                        "name",
                        "description",
                        "is_default",
                        "sort_order",
                        "created_at",
                        "updated_at",
                    ],
                )
                for plan in db.query(models.BudgetPlan)
                .filter(models.BudgetPlan.client_id == client.id)
                .order_by(models.BudgetPlan.sort_order, models.BudgetPlan.id)
                .all()
            ],
            "monthly_plan_lines": [
                row_fields(
                    line,
                    [
                        "id",
                        "target_period",
                        "line_type",
                        "target_type",
                        "target_id",
                        "account_id",
                        "source_account_id",
                        "name",
                        "amount",
                        "source",
                        "source_kind",
                        "identity_key",
                        "manual_override",
                        "cash_treatment",
                        "plan_id",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ],
                )
                for line in db.query(models.MonthlyPlanLine)
                .filter(models.MonthlyPlanLine.client_id == client.id)
                .order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id)
                .all()
            ],
            "period_reviews": [
                row_fields(
                    review,
                    [
                        "id",
                        "start_date",
                        "end_date",
                        "label",
                        "reflection",
                        "next_actions",
                        "created_at",
                        "updated_at",
                    ],
                )
                for review in db.query(models.PeriodReview)
                .filter(models.PeriodReview.client_id == client.id)
                .order_by(models.PeriodReview.start_date, models.PeriodReview.end_date)
                .all()
            ],
            "period_closes": [
                row_fields(close, ["id", "period", "closed_at", "note"])
                for close in db.query(models.PeriodClose).filter_by(client_id=client.id)
                .order_by(models.PeriodClose.period).all()
            ],
            "capsules": [
                {
                    **row_fields(capsule, ["id", "name", "target_amount", "monthly_contribution"]),
                    **row_fields(capsule, [
                        "capsule_type", "target_amount_source",
                        "monthly_contribution_source", "goal_event_id", "created_at",
                    ]),
                }
                for capsule in db.query(models.Capsule)
                .filter(models.Capsule.client_id == client.id)
                .order_by(models.Capsule.id)
                .all()
            ],
            "capsule_drawdowns": [
                row_fields(drawdown, ["id", "capsule_id", "transaction_id", "kind", "amount_minor", "note", "created_at"])
                for drawdown in db.query(models.CapsuleDrawdown)
                .filter(models.CapsuleDrawdown.client_id == client.id)
                .order_by(models.CapsuleDrawdown.id)
                .all()
            ],
            "capsule_funding_sources": [
                row_fields(source, ["id", "capsule_id", "account_id", "target_amount", "max_share_bp", "sort_order", "created_at", "updated_at"])
                for source in db.query(models.CapsuleFundingSource)
                .filter(models.CapsuleFundingSource.client_id == client.id)
                .order_by(models.CapsuleFundingSource.id)
                .all()
            ],
            "capsule_rules": [
                row_fields(
                    rule,
                    [
                        "id",
                        "capsule_id",
                        "trigger_type",
                        "trigger_category",
                        "trigger_description",
                        "trigger_account_id",
                        "source_mode",
                        "source_account_id",
                        "destination_account_id",
                        "amount_type",
                        "amount_value",
                        "is_active",
                        "created_at",
                    ],
                )
                for rule in db.query(models.CapsuleRule)
                .filter(models.CapsuleRule.client_id == client.id)
                .order_by(models.CapsuleRule.id)
                .all()
            ],
            "fx_tracked_currencies": [
                row_fields(row, ["currency", "created_at"])
                for row in db.query(models.FxTrackedCurrency).filter_by(client_id=client.id).order_by(models.FxTrackedCurrency.currency)
            ],
            "exchange_rates": [
                row_fields(
                    rate,
                    [
                        "id",
                        "base_currency",
                        "quote_currency",
                        "rate",
                        "as_of_date",
                        "source",
                        "created_at",
                        "updated_at",
                    ],
                )
                for rate in db.query(models.ExchangeRate)
                .filter(models.ExchangeRate.client_id == client.id)
                .order_by(models.ExchangeRate.id)
                .all()
            ],
            "goal_budget_reflections": [
                row_fields(row, ["id", "scenario_id", "applied_at", "start_period", "end_period", "summary"])
                for row in db.query(models.GoalBudgetReflection).filter_by(client_id=client.id).order_by(models.GoalBudgetReflection.id).all()
            ],
    }

    return {
        "version": EXPORT_VERSION,
        "exported_at": exported_at,
        "manifest": build_manifest(client.id, data, exported_at, _db_revision(db)),
        "client": {
            "id": client.id,
            "name": client.name,
            "username": client.username,
            "email": client.email,
            "general_settings": client.general_settings or {},
        },
        "health": check_data_health(db, client.id),
        "data": data,
    }


def import_client(
    db: Session,
    client: models.Client,
    *,
    data: dict[str, list[dict[str, Any]]],
    version: int | None,
    manifest: dict[str, Any] | None,
) -> dict:
    data = data or {}
    validation = validate_import_payload(data, version, manifest)
    if validation["error_count"]:
        raise Invalid(
            "Import payload validation failed",
            payload={
                "message": "Import payload validation failed",
                "validation": validation,
            },
        )

    data = deepcopy(data)
    if version is None or version < 24:
        moves = migrate_automatic_data(data)
        for code, count in moves.items():
            if count:
                validation["issues"].append({"severity": "warning", "code": code, "detail": f"WP13: {count} rows", "count": count})
                validation["warning_count"] += 1

    legacy_account_returns = {int(row["id"]): row["expected_return"] for row in data.get("accounts", [])
                              if row.get("account_type") == "asset" and row.get("expected_return") is not None}
    if version is None or version < 23:
        data = migrate_account_fields(data, money_client_currency(db, client.id))
    if version is None or version < 26:
        data = migrate_goal_fields(data, date.today().strftime("%Y-%m"))
    if version is None or version < 27:
        data = migrate_goal_v2(data)
    if version is None or version < 28:
        data = migrate_event_fundings(data)
    if version is None or version < 29:
        data = migrate_event_withdrawals(data, money_client_currency(db, client.id))
    if version is None or version < 30:
        data = migrate_plan_records(data, money_client_currency(db, client.id), date.today())

    link_map: dict[int, int] = {}
    scenario_map: dict[int, int] = {}
    account_map: dict[int, int] = {}
    transaction_map: dict[int, int] = {}
    batch_map: dict[int, int] = {}
    event_map: dict[int, int] = {}
    capsule_map: dict[int, int] = {}
    budget_plan_map: dict[int, int] = {}

    try:
        tx_ids = [
            row[0]
            for row in db.query(models.Transaction.id)
            .filter(models.Transaction.client_id == client.id)
            .all()
        ]

        if tx_ids:
            db.query(models.JournalEntry).filter(
                models.JournalEntry.transaction_id.in_(tx_ids)
            ).delete(synchronize_session=False)

        scenario_ids = db.query(models.LifeScenario.id).filter_by(client_id=client.id)
        db.query(models.ScenarioContributionPlan).filter(
            models.ScenarioContributionPlan.scenario_id.in_(scenario_ids),
        ).delete(synchronize_session=False)
        db.query(models.ScenarioAssumptionPeriod).filter(
            models.ScenarioAssumptionPeriod.scenario_id.in_(scenario_ids),
        ).delete(synchronize_session=False)

        for model in [
            models.GoalBudgetReflection,
            models.LifeEventCondition,
            models.HouseholdMember,
            models.LifeEventLink,
            models.ProductDepreciation,
            models.MonthlyPlanLine,
            models.PeriodReview,
            models.PeriodClose,
            models.CapsuleDrawdown,
            models.CapsuleRule,
            models.Capsule,
            models.ExchangeRate,
            models.FxTrackedCurrency,
            models.RegistryEntry,
            models.SimulationConfig,
            models.Product,
            models.Transaction,
            models.TransactionBatch,
            models.BudgetPlan,
            models.LifeEvent,
            models.LifeScenario,
            models.Account,
        ]:
            db.query(model).filter(model.client_id == client.id).delete(
                synchronize_session=False
            )

        db.flush()

        # Legacy backups may contain balance; only their journal is authoritative.
        for item in data.get("accounts", []):
            old_id = int(item["id"])
            account = models.Account(
                client_id=client.id,
                name=item["name"],
                account_type=item["account_type"],
                liability_closing_day=item.get("liability_closing_day"),
                liability_payment_day=item.get("liability_payment_day"),
                liability_payment_month_offset=item.get("liability_payment_month_offset") or 0,
                liability_payment_policy=item.get("liability_payment_policy") or "full",
                liability_minimum_payment_minor=to_minor(item.get("liability_minimum_payment"), money_client_currency(db, client.id)),
                liability_fixed_payment_amount_minor=to_minor(item.get("liability_fixed_payment_amount"), money_client_currency(db, client.id)),
                liability_installment_months=item.get("liability_installment_months"),
                liability_revolving_rate=item.get("liability_revolving_rate"),
                is_active=item.get("is_active", True),
            )
            db.add(account)
            db.flush()
            account_map[old_id] = account.id
        # A client has one budget plan (§8-10): an older backup's other plans and their rows stay out.
        stored_plans = data.get("budget_plans", [])
        kept_plan = next((item for item in stored_plans if item.get("is_default")), stored_plans[0] if stored_plans else None)
        dropped_plan_ids = {int(item["id"]) for item in stored_plans if item is not kept_plan}
        for item in [kept_plan] if kept_plan is not None else []:
            old_id = int(item["id"])
            plan = models.BudgetPlan(
                client_id=client.id,
                name=item["name"],
                description=item.get("description"),
                is_default=True,
                sort_order=item.get("sort_order") or 0,
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_datetime(item.get("updated_at")),
            )
            db.add(plan)
            db.flush()
            budget_plan_map[old_id] = plan.id

        product_map: dict[int, int] = {}
        product_funding_updates: list[tuple[models.Product, int]] = []
        for item in data.get("products", []):
            old_id = int(item["id"])
            product = models.Product(
                client_id=client.id,
                name=item["name"],
                category=item["category"],
                location=item.get("location"),
                last_unit_price_minor=to_minor(item.get("last_unit_price") or 0, money_client_currency(db, client.id)),
                units_per_purchase=item.get("units_per_purchase") or 1,
                frequency_days=item.get("frequency_days") or 0,
                last_purchase_date=parse_date(item.get("last_purchase_date")),
                is_asset=item.get("is_asset", False),
                lifespan_months=item.get("lifespan_months"),
                budget_account_id=account_map.get(item.get("budget_account_id")),
                budget_treatment=item.get("budget_treatment") or "auto",
                purchase_price_minor=to_minor(item.get("purchase_price"), money_client_currency(db, client.id)),
                purchase_date=parse_date(item.get("purchase_date")),
                auto_depreciation=item.get("auto_depreciation", False),
                depreciation_method=item.get("depreciation_method") or "none",
                depreciation_annual_rate=item.get("depreciation_annual_rate"),
                depreciation_interval=item.get("depreciation_interval") or "monthly",
                depreciation_start_date=parse_date(item.get("depreciation_start_date")),
                depreciation_expense_account_id=account_map.get(item.get("depreciation_expense_account_id")),
                depreciation_asset_account_id=account_map.get(item.get("depreciation_asset_account_id")),
            )
            db.add(product)
            db.flush()
            product_map[old_id] = product.id
            if item.get("funding_capsule_id"):
                product_funding_updates.append((product, int(item["funding_capsule_id"])))

        for item in data.get("simulation_configs", []):
            db.add(
                models.SimulationConfig(
                    client_id=client.id,
                    user_id=item.get("user_id", client.id),
                    annual_return=item.get("annual_return", 5.0),
                    tax_rate=item.get("tax_rate", 20.0),
                    is_nisa=item.get("is_nisa", True),
                    volatility=item.get("volatility", 15.0),
                    inflation_rate=item.get("inflation_rate", 2.0),
                    horizon_years=item.get("horizon_years", 30),
                )
            )

        registry_map: dict[int, int] = {}
        for item in data.get("registry_entries", []):
            values = {key: item.get(key) for key in ("name", "kind", "frequency", "frequency_days", "day_of_month", "month_of_year", "repeat_mode", "repeat_count", "note")}
            values.update({key: parse_date(item.get(key)) for key in ("start_date", "end_date", "next_due_date")})
            values.update({key: account_map.get(item.get(key)) for key in ("source_account_id", "destination_account_id", "budget_account_id")})
            entry = models.RegistryEntry(client_id=client.id, **values,
                amount_minor=to_minor(item.get("amount") or 0, item.get("currency") or "JPY"), currency=item.get("currency") or "JPY",
                budget_active=item.get("budget_active", True), is_active=item.get("is_active", True),
                records_transactions=item.get("records_transactions", True),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(), updated_at=parse_datetime(item.get("updated_at")))
            db.add(entry)
            db.flush()
            registry_map[int(item["id"])] = entry.id

        # Older exports carry quick_templates and a batch's quick_template_id;
        # the feature is gone, so both are left behind.
        for item in data.get("transaction_batches", []):
            old_id = int(item["id"])
            batch = models.TransactionBatch(
                client_id=client.id,
                label=item.get("label"),
                source=item.get("source") or "quick",
                input_payload=item.get("input_payload") or {},
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(batch)
            db.flush()
            batch_map[old_id] = batch.id

        if version is not None and version >= 21:
            for item in data.get("life_scenarios", []):
                scenario = models.LifeScenario(
                    client_id=client.id, name=item["name"], annual_return=item.get("annual_return", 5.0),
                    inflation=item.get("inflation", 2.0), horizon_years=item.get("horizon_years", 30),
                    is_goal=item.get("is_goal", False),
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=parse_datetime(item.get("updated_at")) or datetime.utcnow(),
                )
                db.add(scenario)
                db.flush()
                scenario_map[int(item["id"])] = scenario.id
        for item in data.get("goal_budget_reflections", []):
            db.add(models.GoalBudgetReflection(
                client_id=client.id, scenario_id=scenario_map.get(_int_or_none(item.get("scenario_id"))),
                applied_at=parse_datetime(item.get("applied_at")) or datetime.utcnow(),
                start_period=item["start_period"], end_period=item["end_period"], summary=item.get("summary") or {},
            ))
        legacy_graph = version is None or version < 22
        restored_goal = get_goal(db, client.id)
        if legacy_graph and data.get("life_events") and restored_goal is None:
            restored_goal = seed_legacy_goal(db, client.id)

        for item in data.get("life_events", []):
            old_id = int(item["id"])
            event = models.LifeEvent(
                client_id=client.id,
                scenario_id=restored_goal.id if legacy_graph else scenario_map[int(item["scenario_id"])],
                lineage=str(uuid4()) if legacy_graph else item["lineage"],
                name=item["name"],
                target_date=parse_date(item.get("target_date")),
                target_amount_minor=to_minor(item.get("target_amount") or 0, money_client_currency(db, client.id)),
                priority=item.get("priority") or 2,
                note=item.get("note"),
                condition_mode=item.get("condition_mode", "all"),
                direction=item.get("direction", "expense"),
                interest_rate=item.get("interest_rate"),
                repeat_count=item.get("repeat_count"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(event)
            db.flush()
            event_map[old_id] = event.id
        # The records follow the events: a withdrawal names one.
        for item in data.get("scenario_contribution_plans", []) if version is not None and version >= 21 else []:
            db.add(models.ScenarioContributionPlan(
                scenario_id=scenario_map[int(item["scenario_id"])], kind=item.get("kind") or "contribution",
                account_id=account_map[int(item["account_id"])],
                to_account_id=account_map[int(item["to_account_id"])] if item.get("to_account_id") is not None else None,
                start_period=item["start_period"], amount_minor=item.get("amount_minor") or 0,
                interval_months=item.get("interval_months"), repeat_count=item.get("repeat_count"), end_period=item.get("end_period"),
                on_shortage=item.get("on_shortage"), annual_return=item.get("annual_return"), note=item.get("note"),
                life_event_id=event_map[int(item["life_event_id"])] if item.get("life_event_id") is not None else None,
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            ))
        # 期間ごとの前提 arrived in v31 (§8-11); an older backup has none.
        for item in data.get("scenario_assumption_periods", []) if version is not None and version >= 31 else []:
            db.add(models.ScenarioAssumptionPeriod(
                scenario_id=scenario_map[int(item["scenario_id"])], start_period=item["start_period"], end_period=item.get("end_period"),
                annual_return=item.get("annual_return"), inflation=item.get("inflation"), note=item.get("note"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            ))
        # A repayment names its borrowing, which may come later in the payload.
        for item in data.get("life_events", []):
            if item.get("borrowing_event_id") is not None:
                db.get(models.LifeEvent, event_map[int(item["id"])]).borrowing_event_id = event_map.get(_int_or_none(item.get("borrowing_event_id")))

        for item in data.get("life_event_links", []):
            if legacy_graph and item["kind"] == "alternative":
                logging.getLogger(__name__).warning("Converting restored alternative life-event link to after: %s", item["id"])
            link = models.LifeEventLink(
                client_id=client.id,
                from_event_id=event_map[int(item["from_event_id"])],
                to_event_id=event_map[int(item["to_event_id"])],
                kind="after" if legacy_graph else item["kind"], offset_months=item.get("offset_months", 0),
                note=item.get("note"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(link)
            db.flush()
            link_map[int(item["id"])] = link.id

        for item in data.get("transactions", []):
            old_id = int(item["id"])
            transaction = models.Transaction(
                client_id=client.id,
                date=parse_date(item.get("date")),
                description=item["description"],
                amount_minor=Money.from_major(str(item.get("amount") or 0), item.get("currency") or "JPY").minor,
                currency=item.get("currency") or "JPY",
                # from_account_id / to_account_id in a v6 or older payload are
                # ignored: the journal_entries below are the accounts, and they
                # were already required to balance.
                batch_id=batch_map.get(item.get("batch_id")),
                registry_entry_id=registry_map.get(item.get("registry_entry_id")),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(transaction)
            db.flush()
            transaction_map[old_id] = transaction.id

        for item in data.get("product_depreciations", []):
            # Both ends must already be mapped: a posting names a product and
            # the entry that carried it, and is meaningless without either.
            product_id = product_map.get(int(item["product_id"]))
            transaction_id = transaction_map.get(int(item["transaction_id"]))
            if product_id is None or transaction_id is None:
                continue
            db.add(models.ProductDepreciation(
                client_id=client.id, product_id=product_id, transaction_id=transaction_id,
                period=item["period"], amount_minor=int(item["amount_minor"]),
                created_at=parse_datetime(item.get("created_at")),
            ))

        for item in data.get("period_closes", []):
            # Preserve close instants so restoration does not hide late entries.
            db.add(models.PeriodClose(
                client_id=client.id, period=item["period"],
                closed_at=parse_datetime(item["closed_at"]), note=item.get("note"),
            ))

        for item in data.get("period_reviews", []):
            db.add(
                models.PeriodReview(
                    client_id=client.id,
                    start_date=parse_date(item.get("start_date")),
                    end_date=parse_date(item.get("end_date")),
                    label=item.get("label") or "",
                    reflection=item.get("reflection") or "",
                    next_actions=item.get("next_actions") or "",
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=parse_datetime(item.get("updated_at")),
                )
            )

        for item in data.get("capsules", []):
            old_id = int(item["id"])
            capsule = models.Capsule(
                client_id=client.id,
                name=item["name"],
                target_amount_minor=to_minor(item.get("target_amount") or 0, money_client_currency(db, client.id)),
                monthly_contribution_minor=to_minor(item.get("monthly_contribution") or 0, money_client_currency(db, client.id)),
                capsule_type=item.get("capsule_type") or "manual",
                target_amount_source=item.get("target_amount_source") or "manual",
                monthly_contribution_source=item.get("monthly_contribution_source") or "manual",
                goal_event_id=event_map.get(_int_or_none(item.get("goal_event_id"))),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(capsule)
            db.flush()
            capsule_map[old_id] = capsule.id

        for item in data.get("journal_entries", []):
            transaction_id = transaction_map.get(item.get("transaction_id"))
            account_id = account_map.get(item.get("account_id"))
            if transaction_id and account_id:
                transaction = db.get(models.Transaction, transaction_id)
                leg = coerce_leg({**item, "account_id": account_id}, transaction.currency)
                db.add(
                    models.JournalEntry(
                        transaction_id=transaction_id,
                        account_id=account_id,
                        capsule_id=capsule_map.get(item.get("capsule_id")),
                        debit_minor=leg.debit,
                        credit_minor=leg.credit,
                        memo=item.get("memo"),
                        sort_order=item.get("sort_order"),
                    )
                )

        db.flush()
        for transaction_id in transaction_map.values():
            transaction = db.query(models.Transaction).filter(
                models.Transaction.id == transaction_id
            ).one()
            entries = db.query(models.JournalEntry).filter(
                models.JournalEntry.transaction_id == transaction_id
            ).all()
            if len(entries) < 2:
                raise ValueError(f"Transaction {transaction_id} has fewer than two journal entries")
            try:
                validate_legs([
                    Leg(entry.account_id, entry.debit_minor, entry.credit_minor) for entry in entries
                ], transaction.amount_minor)
            except ValueError as exc:
                raise ValueError(f"Transaction {transaction_id}: {exc}") from exc

        for product, old_capsule_id in product_funding_updates:
            product.funding_capsule_id = capsule_map.get(old_capsule_id)



        for item in data.get("capsule_drawdowns", []):
            db.add(models.CapsuleDrawdown(
                client_id=client.id,
                capsule_id=capsule_map[int(item["capsule_id"])],
                transaction_id=transaction_map[int(item["transaction_id"])],
                kind=item["kind"], amount_minor=item["amount_minor"],
                note=item.get("note"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            ))

        for item in data.get("capsule_rules", []):
            capsule_id = capsule_map.get(item.get("capsule_id"))
            if capsule_id:
                db.add(
                    models.CapsuleRule(
                        client_id=client.id,
                        capsule_id=capsule_id,
                        trigger_type=item["trigger_type"],
                        trigger_category=item.get("trigger_category"),
                        trigger_description=item.get("trigger_description"),
                        trigger_account_id=account_map.get(item.get("trigger_account_id")),
                        source_mode=item.get("source_mode") or "transaction_account",
                        source_account_id=account_map.get(item.get("source_account_id")),
                        destination_account_id=account_map.get(item.get("destination_account_id")),
                        amount_type=item.get("amount_type") or "fixed",
                        **rule_amount_fields(item.get("amount_value") or 0, item.get("amount_type") or "fixed", money_client_currency(db, client.id)),
                        is_active=item.get("is_active", True),
                        created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    )
                )

        for item in data.get("capsule_funding_sources", []):
            capsule_id = capsule_map.get(item.get("capsule_id"))
            account_id = account_map.get(item.get("account_id"))
            if capsule_id and account_id:
                db.add(
                    models.CapsuleFundingSource(
                        client_id=client.id,
                        capsule_id=capsule_id,
                        account_id=account_id,
                        target_amount_minor=to_minor(
                            item.get("target_amount") or 0, money_client_currency(db, client.id),
                        ),
                        sort_order=item.get("sort_order") or 0,
                        max_share_bp=item.get("max_share_bp"),
                        created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_datetime(item.get("updated_at")) or datetime.utcnow(),
                    )
                )

        monthly_plan_line_map: dict[int, int] = {}
        active_plan_line_identities: dict[str, models.MonthlyPlanLine] = {}
        for item in data.get("monthly_plan_lines", []):
            if item.get("plan_id") is not None and int(item["plan_id"]) in dropped_plan_ids:
                continue
            old_id = int(item["id"])
            target_type = item.get("target_type") or "manual"
            target_id = item.get("target_id")
            if target_type == "capsule":
                target_id = capsule_map.get(target_id)
            elif target_type == "product":
                target_id = product_map.get(target_id)
            elif target_type == "account":
                target_id = account_map.get(target_id)
            account_id = account_map.get(item.get("account_id"))
            source_account_id = account_map.get(item.get("source_account_id"))
            source_kind = item.get("source_kind") or item.get("source") or "manual"
            if source_kind == "recurrence":
                source_kind = "recurring"
            line = models.MonthlyPlanLine(
                client_id=client.id,
                target_period=item["target_period"],
                line_type=item["line_type"],
                target_type=target_type,
                target_id=target_id,
                account_id=account_id,
                source_account_id=source_account_id,
                name=item.get("name"),
                amount_minor=to_minor(item.get("amount") or 0, money_client_currency(db, client.id)),
                source=item.get("source") or "manual",
                source_kind=source_kind,
                manual_override=item.get("manual_override", False),
                cash_treatment=item.get("cash_treatment") or "auto",
                plan_id=budget_plan_map.get(item.get("plan_id")),
                is_active=item.get("is_active", True),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_datetime(item.get("updated_at")),
            )
            assign_plan_line_identity(line)
            if line.is_active and line.identity_key:
                previous = active_plan_line_identities.get(line.identity_key)
                if previous:
                    previous.is_active = False
                    db.flush()
                active_plan_line_identities[line.identity_key] = line
            db.add(line)
            db.flush()
            monthly_plan_line_map[old_id] = line.id

        for item in data.get("fx_tracked_currencies", []):
            db.add(models.FxTrackedCurrency(client_id=client.id, currency=item["currency"],
                                           created_at=parse_datetime(item.get("created_at")) or datetime.utcnow()))

        for item in data.get("exchange_rates", []):
            db.add(
                models.ExchangeRate(
                    client_id=client.id,
                    base_currency=(item.get("base_currency") or "JPY").upper(),
                    quote_currency=(item.get("quote_currency") or "JPY").upper(),
                    rate=item.get("rate") or 1.0,
                    as_of_date=parse_date(item.get("as_of_date")) or date.today(),
                    source=item.get("source") or "manual",
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=parse_datetime(item.get("updated_at")),
                )
            )

        if version is None or version < 21:
            period = date.today().strftime("%Y-%m")
            for scenario in db.query(models.LifeScenario).filter_by(client_id=client.id):
                for old_id, rate in legacy_account_returns.items():
                    db.add(models.ScenarioContributionPlan(scenario_id=scenario.id, kind="contribution", account_id=account_map[old_id],
                                                           start_period=period, amount_minor=0, interval_months=1, annual_return=rate))

        member_map: dict[int, int] = {}
        for item in data.get("household_members", []):
            member = models.HouseholdMember(
                client_id=client.id, name=item["name"], relation=item.get("relation"),
                birth_date=parse_date(item["birth_date"]),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(member)
            db.flush()
            member_map[int(item["id"])] = member.id
        condition_reference_maps = {
            "account_balance": account_map, "capsule_claim": capsule_map,
            "goal_progress": event_map, "member_age": member_map,
        }
        for item in data.get("life_event_conditions", []):
            # Never keep a dangling source id: it might identify an unrelated restored fact.
            reference_id = condition_reference_maps.get(item["metric"], {}).get(item.get("reference_id"))
            db.add(models.LifeEventCondition(
                client_id=client.id, life_event_id=event_map[int(item["life_event_id"])],
                metric=item["metric"], comparator=item["comparator"],
                threshold_minor=item.get("threshold_minor"), threshold_number=item.get("threshold_number"),
                threshold_date=parse_date(item.get("threshold_date")), reference_id=reference_id,
                note=item.get("note"), created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            ))

        if legacy_graph and restored_goal is not None:
            # A shared graph was every story; copies are made after all children exist.
            db.flush()
            for story in db.query(models.LifeScenario).filter(
                models.LifeScenario.client_id == client.id, models.LifeScenario.id != restored_goal.id,
            ).all():
                copy_graph(db, client.id, restored_goal.id, story.id)

        db.commit()
        invalidate_client(client.id)
    except Exception as exc:
        db.rollback()
        raise Invalid(f"Import failed: {exc}") from exc

    return {
        "status": "ok",
        "message": "Data imported successfully",
        "counts": data_counts(data),
        "validation": validation,
        "health": check_data_health(db, client.id),
    }
