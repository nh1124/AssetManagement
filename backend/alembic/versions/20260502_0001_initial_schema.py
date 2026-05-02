"""initial_schema

Revision ID: 20260502_0001
Revises:
Create Date: 2026-05-02 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260502_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> list[sa.Table]:
    metadata = sa.MetaData()

    clients = sa.Table(
        "clients",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("ai_config", sa.JSON(), nullable=True),
        sa.Column("general_settings", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    accounts = sa.Table(
        "accounts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("account_type", sa.String(), nullable=True),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("expected_return", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("client_id", "name", name="_client_account_uc"),
    )
    transactions = sa.Table(
        "transactions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("from_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("to_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    products = sa.Table(
        "products",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("last_unit_price", sa.Float(), nullable=True),
        sa.Column("units_per_purchase", sa.Integer(), nullable=True),
        sa.Column("frequency_days", sa.Integer(), nullable=True),
        sa.Column("last_purchase_date", sa.Date(), nullable=True),
        sa.Column("is_asset", sa.Boolean(), nullable=True),
        sa.Column("lifespan_months", sa.Integer(), nullable=True),
        sa.Column("purchase_price", sa.Float(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
    )
    simulation_configs = sa.Table(
        "simulation_configs",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("annual_return", sa.Float(), nullable=True),
        sa.Column("tax_rate", sa.Float(), nullable=True),
        sa.Column("is_nisa", sa.Boolean(), nullable=True),
        sa.Column("monthly_savings", sa.Float(), nullable=True),
        sa.Column("volatility", sa.Float(), nullable=True),
        sa.Column("inflation_rate", sa.Float(), nullable=True),
    )
    recurring_transactions = sa.Table(
        "recurring_transactions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("from_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("to_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("frequency", sa.String(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("month_of_year", sa.Integer(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    life_events = sa.Table(
        "life_events",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("target_amount", sa.Float(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    goal_allocations = sa.Table(
        "goal_allocations",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "life_event_id",
            sa.Integer(),
            sa.ForeignKey("life_events.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("allocation_percentage", sa.Float(), nullable=True),
        sa.UniqueConstraint(
            "life_event_id",
            "account_id",
            name="_goal_allocation_event_account_uc",
        ),
    )
    monthly_budgets = sa.Table(
        "monthly_budgets",
        metadata,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("target_period", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.UniqueConstraint("account_id", "target_period", name="_account_period_uc"),
    )
    monthly_reviews = sa.Table(
        "monthly_reviews",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("target_period", sa.String(), nullable=False),
        sa.Column("reflection", sa.Text(), nullable=True),
        sa.Column("next_actions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "target_period", name="_client_review_period_uc"),
    )
    milestones = sa.Table(
        "milestones",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column(
            "life_event_id",
            sa.Integer(),
            sa.ForeignKey("life_events.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("target_amount", sa.Float(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    capsules = sa.Table(
        "capsules",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("target_amount", sa.Float(), nullable=True),
        sa.Column("monthly_contribution", sa.Float(), nullable=True),
        sa.Column("current_balance", sa.Float(), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    journal_entries = sa.Table(
        "journal_entries",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("debit", sa.Float(), nullable=True),
        sa.Column("credit", sa.Float(), nullable=True),
    )

    for table, column, unique in [
        (clients, "id", False),
        (clients, "name", True),
        (clients, "username", True),
        (clients, "email", True),
        (accounts, "id", False),
        (accounts, "name", False),
        (transactions, "id", False),
        (products, "id", False),
        (products, "name", False),
        (simulation_configs, "id", False),
        (recurring_transactions, "id", False),
        (recurring_transactions, "name", False),
        (life_events, "id", False),
        (life_events, "name", False),
        (goal_allocations, "id", False),
        (monthly_reviews, "id", False),
        (milestones, "id", False),
        (capsules, "id", False),
        (capsules, "name", False),
        (journal_entries, "id", False),
    ]:
        sa.Index(f"ix_{table.name}_{column}", table.c[column], unique=unique)

    return [
        clients,
        accounts,
        transactions,
        products,
        simulation_configs,
        recurring_transactions,
        life_events,
        goal_allocations,
        monthly_budgets,
        monthly_reviews,
        milestones,
        capsules,
        journal_entries,
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)
    for table in _tables():
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
