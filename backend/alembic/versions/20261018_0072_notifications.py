"""One notifications table for everything that needs the user's attention."""
from alembic import op
import sqlalchemy as sa

revision = "20261018_0072"
down_revision = "20261018_0071"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "dedupe_key", name="uq_notifications_client_key"),
        sa.CheckConstraint("status IN ('open', 'snoozed', 'dismissed', 'done')", name="ck_notifications_status"),
    )
    op.create_index("ix_notifications_client_id", "notifications", ["client_id"])
    # The goal reminders lived in monthly_actions as a confirmation-only kind; they are
    # notifications now and are regenerated on the next screen open.
    op.execute("DELETE FROM monthly_actions WHERE kind = 'goal_reflection'")


def downgrade():
    op.drop_index("ix_notifications_client_id", table_name="notifications")
    op.drop_table("notifications")
