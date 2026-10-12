"""Store fixed per-account capsule funding plans, without changing balances."""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20261013_0054"
down_revision = "20261012_0053"
branch_labels = None
depends_on = None


def _verify_seed(connection, capsules, sources):
    expected = connection.scalar(sa.select(sa.func.count()).select_from(capsules).where(
        capsules.c.account_id.is_not(None),
    ))
    actual = connection.scalar(sa.select(sa.func.count()).select_from(sources))
    if actual != expected:
        raise ValueError(f"Capsule funding seed count mismatch: expected {expected}, got {actual}")
    # Also verify owner/account correspondence, so equal counts cannot hide a missing capsule.
    mismatch = connection.execute(sa.select(capsules.c.id).select_from(
        capsules.outerjoin(sources, sources.c.capsule_id == capsules.c.id),
    ).where(capsules.c.account_id.is_not(None), sa.or_(
        sources.c.id.is_(None),
        sources.c.client_id != capsules.c.client_id,
        sources.c.account_id != capsules.c.account_id,
        sources.c.target_amount_minor != sa.func.coalesce(capsules.c.target_amount_minor, 0),
        sources.c.sort_order != 0,
    ))).first()
    if mismatch:
        raise ValueError(f"Capsule funding seed mismatch for capsule {mismatch[0]}")


def upgrade():
    op.create_table(
        "capsule_funding_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("capsule_id", sa.Integer(), sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("target_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("capsule_id", "account_id", name="uq_capsule_funding_sources_account"),
    )
    op.create_index("ix_capsule_funding_sources_capsule_id", "capsule_funding_sources", ["capsule_id"])
    op.add_column("accounts", sa.Column("max_capsule_share_bp", sa.Integer(), nullable=True))

    connection = op.get_bind()
    metadata = sa.MetaData()
    capsules = sa.Table("capsules", metadata, autoload_with=connection)
    sources = sa.Table("capsule_funding_sources", metadata, autoload_with=connection)
    now = datetime.utcnow()
    connection.execute(sources.insert().from_select(
        ["client_id", "capsule_id", "account_id", "target_amount_minor", "sort_order", "created_at", "updated_at"],
        sa.select(
            capsules.c.client_id, capsules.c.id, capsules.c.account_id,
            sa.func.coalesce(capsules.c.target_amount_minor, 0), sa.literal(0),
            sa.literal(now), sa.literal(now),
        ).where(capsules.c.account_id.is_not(None)),
    ))
    _verify_seed(connection, capsules, sources)


def downgrade():
    op.drop_column("accounts", "max_capsule_share_bp")
    op.drop_table("capsule_funding_sources")
