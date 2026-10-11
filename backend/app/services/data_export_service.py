from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..domain.transfer import EXPORT_VERSION, build_manifest, row_fields
from .data_health_service import check_data_health


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
                        "balance",
                        "parent_id",
                        "expected_return",
                        "role",
                        "role_target_amount",
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
                    ],
                )
                for product in db.query(models.Product)
                .filter(models.Product.client_id == client.id)
                .order_by(models.Product.id)
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
                        "monthly_savings",
                        "volatility",
                        "inflation_rate",
                    ],
                )
                for config in db.query(models.SimulationConfig)
                .filter(models.SimulationConfig.client_id == client.id)
                .order_by(models.SimulationConfig.id)
                .all()
            ],
            "recurring_transactions": [
                row_fields(
                    item,
                    [
                        "id",
                        "name",
                        "amount",
                        "currency",
                        "from_account_id",
                        "to_account_id",
                        "frequency",
                        "day_of_month",
                        "month_of_year",
                        "next_due_date",
                        "start_period",
                        "end_period",
                        "auto_post",
                        "is_active",
                        "source_registry_entry_id",
                        "created_at",
                    ],
                )
                for item in db.query(models.RecurringTransaction)
                .filter(models.RecurringTransaction.client_id == client.id)
                .order_by(models.RecurringTransaction.id)
                .all()
            ],
            "registry_entries": [
                row_fields(
                    item,
                    [
                        "id",
                        "name",
                        "entry_type",
                        "category",
                        "amount",
                        "currency",
                        "frequency",
                        "frequency_days",
                        "day_of_month",
                        "month_of_year",
                        "line_type",
                        "budget_account_id",
                        "source_account_id",
                        "destination_account_id",
                        "funding_capsule_id",
                        "budget_treatment",
                        "generate_recurring",
                        "budget_active",
                        "is_active",
                        "source_product_id",
                        "source_recurring_transaction_id",
                        "note",
                        "start_period",
                        "end_period",
                        "created_at",
                        "updated_at",
                    ],
                )
                for item in db.query(models.RegistryEntry)
                .filter(models.RegistryEntry.client_id == client.id)
                .order_by(models.RegistryEntry.id)
                .all()
            ],
            "quick_templates": [
                row_fields(
                    item,
                    [
                        "id",
                        "tray",
                        "name",
                        "template_kind",
                        "description",
                        "category",
                        "default_currency",
                        "default_from_account_id",
                        "default_to_account_id",
                        "config",
                        "sort_order",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ],
                )
                for item in db.query(models.QuickTemplate)
                .filter(models.QuickTemplate.client_id == client.id)
                .order_by(models.QuickTemplate.id)
                .all()
            ],
            "transaction_batches": [
                row_fields(
                    item,
                    [
                        "id",
                        "quick_template_id",
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
                        "name",
                        "start_date",
                        "target_date",
                        "target_amount",
                        "priority",
                        "note",
                        "active_plan_basis",
                        "active_plan_label",
                        "plan_status_override",
                        "created_at",
                    ],
                )
                for event in db.query(models.LifeEvent)
                .filter(models.LifeEvent.client_id == client.id)
                .order_by(models.LifeEvent.id)
                .all()
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
                        "recurring_transaction_id",
                        "created_at",
                    ],
                )
                for transaction in db.query(models.Transaction)
                .filter(models.Transaction.client_id == client.id)
                .order_by(models.Transaction.id)
                .all()
            ],
            "journal_entries": [
                row_fields(entry, ["id", "transaction_id", "account_id", "debit", "credit", "memo", "sort_order"])
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
            "monthly_actions": [
                row_fields(
                    action,
                    [
                        "id",
                        "source_period",
                        "target_period",
                        "proposal_id",
                        "kind",
                        "description",
                        "amount",
                        "target_id",
                        "payload",
                        "result",
                        "status",
                        "idempotency_key",
                        "created_at",
                        "applied_at",
                    ],
                )
                for action in db.query(models.MonthlyAction)
                .filter(models.MonthlyAction.client_id == client.id)
                .order_by(models.MonthlyAction.id)
                .all()
            ],
            "milestones": [
                row_fields(
                    milestone,
                    [
                        "id",
                        "life_event_id",
                        "date",
                        "target_amount",
                        "note",
                        "source",
                        "source_snapshot",
                        "is_active_plan",
                        "created_at",
                    ],
                )
                for milestone in db.query(models.Milestone)
                .filter(models.Milestone.client_id == client.id)
                .order_by(models.Milestone.id)
                .all()
            ],
            "capsules": [
                row_fields(
                    capsule,
                    [
                        "id",
                        "name",
                        "target_amount",
                        "monthly_contribution",
                        "current_balance",
                        "account_id",
                        "life_event_id",
                        "capsule_type",
                        "target_amount_source",
                        "monthly_contribution_source",
                        "created_at",
                    ],
                )
                for capsule in db.query(models.Capsule)
                .filter(models.Capsule.client_id == client.id)
                .order_by(models.Capsule.id)
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
                        "source_mode",
                        "source_account_id",
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
            "capsule_holdings": [
                row_fields(holding, ["id", "capsule_id", "account_id", "held_amount", "note", "updated_at"])
                for holding in db.query(models.CapsuleHolding)
                .join(models.Capsule, models.Capsule.id == models.CapsuleHolding.capsule_id)
                .filter(models.Capsule.client_id == client.id)
                .order_by(models.CapsuleHolding.id)
                .all()
            ],
            "simulation_scenarios": [
                row_fields(
                    scenario,
                    [
                        "id",
                        "life_event_id",
                        "name",
                        "description",
                        "annual_return",
                        "inflation",
                        "monthly_savings",
                        "contribution_schedule",
                        "allocation_mode",
                        "created_at",
                        "updated_at",
                    ],
                )
                for scenario in db.query(models.SimulationScenario)
                .filter(models.SimulationScenario.client_id == client.id)
                .order_by(models.SimulationScenario.id)
                .all()
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

