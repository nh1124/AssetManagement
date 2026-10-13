"""Record the reason for a capsule drawdown without guessing past intent."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0058"
down_revision = "20261013_0057"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "capsule_drawdowns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("capsule_id", sa.Integer(), sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("capsule_id", "transaction_id", name="uq_capsule_drawdowns_transaction"),
        sa.CheckConstraint("kind IN ('as_intended', 'diverted')", name="ck_capsule_drawdown_kind"),
    )
    op.create_index("ix_capsule_drawdowns_capsule_id", "capsule_drawdowns", ["capsule_id"])


def downgrade():
    op.drop_table("capsule_drawdowns")
