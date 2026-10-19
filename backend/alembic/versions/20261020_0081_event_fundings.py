"""Which accounts pay a life event move from the event to the simulation settings (WP21).

life_event_fundings: a share (basis points) of an event per asset account. Each event's
account becomes one funding of the whole event; then life_events.account_id is dropped.

Revision ID: 20261020_0081
Revises: 20261020_0080
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_0081"
down_revision = "20261020_0080"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.create_table(
        "life_event_fundings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("share_bp", sa.Integer(), nullable=False),
        sa.UniqueConstraint("life_event_id", "account_id", name="uq_life_event_fundings_account"),
        sa.CheckConstraint("share_bp > 0 AND share_bp <= 10000", name="ck_life_event_fundings_share"),
    )
    moved = bind.execute(sa.text(
        "INSERT INTO life_event_fundings (life_event_id, account_id, share_bp) "
        "SELECT life_events.id, life_events.account_id, 10000 FROM life_events "
        "JOIN accounts ON accounts.id = life_events.account_id AND accounts.account_type = 'asset'"
    )).rowcount
    with op.batch_alter_table("life_events") as batch:
        batch.drop_constraint("fk_life_events_account_id", type_="foreignkey")
        batch.drop_column("account_id")
    print("WP21 migration counts:", {"event_accounts_moved": moved})


def downgrade():
    bind = op.get_bind()
    with op.batch_alter_table("life_events") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_life_events_account_id", "accounts", ["account_id"], ["id"], ondelete="SET NULL")
    # An event keeps the account with its largest share.
    bind.execute(sa.text(
        "UPDATE life_events SET account_id = (SELECT f.account_id FROM life_event_fundings f WHERE f.life_event_id = life_events.id "
        "ORDER BY f.share_bp DESC, f.id LIMIT 1)"
    ))
    op.drop_table("life_event_fundings")
