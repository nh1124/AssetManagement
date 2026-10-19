"""WP12: flatten accounts, preserve scenario yields, track FX currencies."""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20261019_0075"
down_revision = "20261019_0074"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Refuse an unexpected legacy kind rather than erase a user's journal.
    if bind.execute(sa.text("SELECT count(*) FROM accounts WHERE account_type = 'item'")).scalar():
        raise RuntimeError("WP12 requires accounts of type item to be migrated explicitly")
    bind.execute(sa.text("""
        INSERT INTO life_scenario_account_returns (scenario_id, account_id, annual_return)
        SELECT s.id, a.id, a.expected_return
        FROM accounts a JOIN life_scenarios s ON s.client_id = a.client_id
        WHERE a.account_type = 'asset' AND a.expected_return IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM life_scenario_account_returns r
                          WHERE r.scenario_id = s.id AND r.account_id = a.id)
    """))
    op.create_table(
        "fx_tracked_currencies",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), primary_key=True),
        sa.Column("currency", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_id", "currency", name="uq_fx_tracked_client_currency"),
    )
    clients = sa.table("clients", sa.column("id", sa.Integer()), sa.column("general_settings", sa.JSON()))
    rates = sa.table("exchange_rates", sa.column("client_id"), sa.column("base_currency"), sa.column("quote_currency"))
    tracked = sa.table("fx_tracked_currencies", sa.column("client_id"), sa.column("currency"), sa.column("created_at"))
    for client_id, settings in bind.execute(sa.select(clients.c.id, clients.c.general_settings)):
        base = ((settings or {}).get("currency") or "JPY").strip().upper()
        currencies = {code.strip().upper() for pair in bind.execute(sa.select(rates.c.base_currency, rates.c.quote_currency).where(rates.c.client_id == client_id)) for code in pair}
        for currency in sorted(currencies - {base}):
            bind.execute(tracked.insert().values(client_id=client_id, currency=currency, created_at=datetime.utcnow()))
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("accounts", naming_convention=naming) as batch:
        for fk in sa.inspect(bind).get_foreign_keys("accounts"):
            if fk["constrained_columns"] == ["parent_id"]:
                batch.drop_constraint(fk["name"] or "fk_accounts_parent_id_accounts", type_="foreignkey")
        batch.drop_constraint("ck_accounts_institution", type_="check")
        batch.drop_constraint("ck_accounts_withdrawable_from_age", type_="check")
        for column in ("role", "role_target_amount_minor", "institution", "withdrawable_from_age", "parent_id", "expected_return"):
            batch.drop_column(column)
        batch.create_check_constraint("ck_accounts_type", "account_type IN ('asset', 'liability', 'income', 'expense')")


def downgrade():
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_type", type_="check")
        batch.add_column(sa.Column("role", sa.String(), nullable=False, server_default="unassigned"))
        batch.add_column(sa.Column("role_target_amount_minor", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("institution", sa.String(), nullable=False, server_default="none"))
        batch.add_column(sa.Column("withdrawable_from_age", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("expected_return", sa.Float(), nullable=True))
        batch.create_foreign_key("accounts_parent_id_fkey", "accounts", ["parent_id"], ["id"])
        batch.create_check_constraint("ck_accounts_institution", "institution IN ('none', 'nisa_tsumitate', 'nisa_growth', 'ideco', 'dc_corporate', 'tokutei_withholding', 'tokutei_self', 'general')")
        batch.create_check_constraint("ck_accounts_withdrawable_from_age", "withdrawable_from_age IS NULL OR withdrawable_from_age >= 0")
    op.drop_table("fx_tracked_currencies")
