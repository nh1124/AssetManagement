"""add a separate transaction proposal queue

Unapproved entries must stay outside transactions so reports continue to read
only posted ledger entries without filtering a second source of truth by status.

Revision ID: 20261011_0049
Revises: 20261011_0048
Create Date: 2026-10-11
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261011_0049"
down_revision: Union[str, None] = "20261011_0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("origin_ref", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="JPY"),
        sa.Column("legs", sa.JSON(), nullable=False),
        # Retain the proposal if its cause is deleted.
        sa.Column("trigger_transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        # Retain the proposal if its posted result is deleted.
        sa.Column("posted_transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by_client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.UniqueConstraint("client_id", "idempotency_key", name="_client_transaction_proposal_idempotency_uc"),
    )
    for column in ("client_id", "status", "trigger_transaction_id"):
        op.create_index(f"ix_transaction_proposals_{column}", "transaction_proposals", [column])


def downgrade() -> None:
    op.drop_table("transaction_proposals")
