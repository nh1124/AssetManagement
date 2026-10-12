"""Retire unbacked holdings, the single account and the unused balance cache."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0057"
down_revision = "20261013_0056"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Hold the PostgreSQL table lock through the drop so a concurrent claim
    # cannot be inserted after the emptiness check. Check before any DDL.
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("LOCK TABLE capsule_holdings IN ACCESS EXCLUSIVE MODE"))
    count = connection.scalar(sa.text("SELECT COUNT(*) FROM capsule_holdings"))
    if count:
        raise ValueError(f"Refusing to discard {count} capsule holding(s); capsule_holdings must be empty")
    account_fk = next(fk for fk in sa.inspect(connection).get_foreign_keys("capsules")
                      if fk["constrained_columns"] == ["account_id"])
    op.drop_table("capsule_holdings")
    with op.batch_alter_table("capsules", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}) as batch:
        batch.drop_constraint(account_fk["name"] or "fk_capsules_account_id_accounts", type_="foreignkey")
        batch.drop_column("account_id")
        batch.drop_column("current_balance_minor")


def downgrade():
    # These retired values cannot be recovered: the cache restores as zero,
    # and the holding table restores empty, matching their state at retirement.
    with op.batch_alter_table("capsules") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("current_balance_minor", sa.BigInteger(), nullable=True))
        batch.create_foreign_key("fk_capsules_account_id_accounts", "accounts", ["account_id"], ["id"])
    op.execute(sa.text("""
        UPDATE capsules SET current_balance_minor = 0, account_id = (
            SELECT account_id FROM capsule_funding_sources
            WHERE capsule_id = capsules.id ORDER BY sort_order, id LIMIT 1
        )
    """))
    op.create_table(
        "capsule_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capsule_id", sa.Integer(), sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("held_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_capsule_holdings_capsule_id", "capsule_holdings", ["capsule_id"])
