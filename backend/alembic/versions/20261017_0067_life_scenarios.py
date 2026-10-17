"""Persist user-authored life scenarios and migrate the adopted branch."""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20261017_0067"
down_revision = "20261017_0066"
branch_labels = None
depends_on = None


def upgrade():
    scenarios = op.create_table(
        "life_scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("annual_return", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("inflation", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("horizon_years", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_goal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("client_id", "name", name="uq_life_scenarios_name"),
        sa.CheckConstraint("horizon_years BETWEEN 1 AND 60", name="ck_life_scenarios_horizon_years"),
    )
    op.create_index("uq_life_scenarios_goal", "life_scenarios", ["client_id"], unique=True,
                    postgresql_where=sa.text("is_goal"), sqlite_where=sa.text("is_goal"))
    choices = op.create_table(
        "life_scenario_choices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("life_event_links.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("scenario_id", "link_id", name="uq_life_scenario_choices_link"),
    )
    returns = op.create_table(
        "life_scenario_account_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("annual_return", sa.Float(), nullable=False),
        sa.UniqueConstraint("scenario_id", "account_id", name="uq_life_scenario_account_returns_account"),
    )
    bind = op.get_bind()
    events = sa.table("life_events", sa.column("id"), sa.column("client_id"), sa.column("name"))
    links = sa.table("life_event_links", sa.column("id"), sa.column("client_id"),
                     sa.column("to_event_id"), sa.column("kind"), sa.column("adopted", sa.Boolean()))
    configs = sa.table("simulation_configs", sa.column("id"), sa.column("client_id"),
                       sa.column("annual_return"), sa.column("inflation_rate"), sa.column("horizon_years"))
    accounts = sa.table("accounts", sa.column("id"), sa.column("client_id"),
                        sa.column("account_type"), sa.column("expected_return"))
    for client_id in bind.execute(sa.select(events.c.client_id).where(events.c.client_id.isnot(None)).distinct()).scalars():
        config = bind.execute(sa.select(configs).where(configs.c.client_id == client_id).order_by(configs.c.id)).mappings().first()
        chosen = bind.execute(sa.select(links.c.id, events.c.name).join(
            events, events.c.id == links.c.to_event_id,
        ).where(links.c.client_id == client_id, links.c.kind == "alternative", links.c.adopted.is_(True)).order_by(links.c.id)).all()
        now = datetime.utcnow()
        scenario_id = bind.execute(scenarios.insert().values(
            client_id=client_id, name=" ／ ".join(row.name for row in chosen) or "基本シナリオ",
            annual_return=config["annual_return"] if config and config["annual_return"] is not None else 5.0,
            inflation=config["inflation_rate"] if config and config["inflation_rate"] is not None else 2.0,
            horizon_years=config["horizon_years"] if config else 30,
            is_goal=True, created_at=now, updated_at=now,
        )).inserted_primary_key[0]
        for link_id, _ in chosen:
            bind.execute(choices.insert().values(scenario_id=scenario_id, link_id=link_id))
        for account in bind.execute(sa.select(accounts).where(
            accounts.c.client_id == client_id, accounts.c.account_type == "asset", accounts.c.expected_return.isnot(None),
        )).mappings():
            bind.execute(returns.insert().values(scenario_id=scenario_id, account_id=account["id"], annual_return=account["expected_return"]))
    op.drop_column("life_event_links", "adopted")


def downgrade():
    op.add_column("life_event_links", sa.Column("adopted", sa.Boolean(), nullable=False, server_default=sa.false()))
    # EXISTS avoids relying on dialect-specific UPDATE ... FROM syntax.
    op.execute(sa.text("""
        UPDATE life_event_links SET adopted = true
        WHERE EXISTS (
            SELECT 1 FROM life_scenario_choices c
            JOIN life_scenarios s ON s.id = c.scenario_id
            WHERE c.link_id = life_event_links.id AND s.is_goal = true
              AND s.client_id = life_event_links.client_id
        )
    """))
    op.drop_table("life_scenario_account_returns")
    op.drop_table("life_scenario_choices")
    op.drop_index("uq_life_scenarios_goal", table_name="life_scenarios")
    op.drop_table("life_scenarios")
