"""drop the untyped plan-line source reference

source_id depended on source_kind and duplicated target_id or account_id for
current generated lines. Matching uses the surviving typed fields. Rewrite
all identity keys in the same transaction so the unique index compares the
application's compact JSON format throughout.

Downgrade restores the nullable column and index, but does not restore its
values; keys are rewritten with the application's function again.

Revision ID: 20261011_0048
Revises: 20261011_0047
Create Date: 2026-10-11
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.services.budget_lines import plan_line_identity_key

revision: str = "20261011_0048"
down_revision: Union[str, None] = "20261011_0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rewrite_identity_keys() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT id, plan_id, target_period, source, source_kind, line_type, "
        "target_type, target_id, account_id, source_account_id, name, "
        "cash_treatment, is_active FROM monthly_plan_lines"
    )).mappings().all()
    updates = []
    active_keys: dict[str, int] = {}
    for row in rows:
        key = plan_line_identity_key(dict(row))
        if row["is_active"] and key:
            if key in active_keys:
                raise RuntimeError(
                    f"Plan-line identity collision: ids {active_keys[key]} and {row['id']}, key={key}"
                )
            active_keys[key] = row["id"]
        updates.append({"id": row["id"], "identity_key": key})
    if updates:
        connection.execute(sa.text(
            "UPDATE monthly_plan_lines SET identity_key = :identity_key WHERE id = :id"
        ), updates)


def upgrade() -> None:
    _rewrite_identity_keys()
    op.drop_index("ix_monthly_plan_lines_source_identity", table_name="monthly_plan_lines")
    op.drop_column("monthly_plan_lines", "source_id")


def downgrade() -> None:
    op.add_column("monthly_plan_lines", sa.Column("source_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_monthly_plan_lines_source_identity",
        "monthly_plan_lines",
        ["client_id", "plan_id", "target_period", "source_kind", "source_id"],
    )
    _rewrite_identity_keys()
