"""Give each scenario its own story while keeping goal capsules on originals."""
from datetime import datetime
import logging
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "20261017_0068"
down_revision = "20261017_0067"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")


def _remap(value, event_map, link_map):
    if isinstance(value, list):
        return [_remap(item, event_map, link_map) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        mapping = event_map if key in {"life_event_id", "event_id"} else link_map if key == "link_id" else None
        result[key] = mapping.get(item, item) if mapping is not None and isinstance(item, int) else _remap(item, event_map, link_map)
    return result


def upgrade():
    op.add_column("life_events", sa.Column("scenario_id", sa.Integer(), nullable=True))
    op.add_column("life_events", sa.Column("lineage", sa.String(36), nullable=True))
    bind = op.get_bind()
    metadata = sa.MetaData()
    tables = {name: sa.Table(name, metadata, autoload_with=bind) for name in (
        "life_events", "life_event_links", "life_event_conditions", "milestones",
        "life_scenarios", "life_scenario_account_returns", "accounts",
    )}
    events, links = tables["life_events"], tables["life_event_links"]
    scenarios, returns, accounts = (tables[name] for name in (
        "life_scenarios", "life_scenario_account_returns", "accounts",
    ))
    alternatives = bind.execute(sa.select(links.c.id).where(links.c.kind == "alternative")).scalars().all()
    if alternatives:
        log.warning("Converting alternative life-event links to after: %s", alternatives)
        bind.execute(links.update().where(links.c.kind == "alternative").values(kind="after"))

    client_ids = bind.execute(sa.select(events.c.client_id).distinct()).scalars().all()
    for client_id in client_ids:
        if client_id is None:
            # No client can own an orphan graph; fail before enforcing a bogus owner.
            raise RuntimeError("life_events without client_id must be assigned to a client before N1a")
        stories = bind.execute(sa.select(scenarios).where(scenarios.c.client_id == client_id).order_by(scenarios.c.id)).mappings().all()
        goal = next((row for row in stories if row["is_goal"]), None)
        if goal is None:
            names = {row["name"] for row in stories}
            name, suffix = "基本シナリオ", 2
            while name in names:
                name = f"基本シナリオ ({suffix})"
                suffix += 1
            now = datetime.utcnow()
            goal_id = bind.execute(scenarios.insert().values(
                client_id=client_id, name=name, annual_return=5.0, inflation=2.0,
                horizon_years=30, is_goal=True, created_at=now, updated_at=now,
            )).inserted_primary_key[0]
            for account in bind.execute(sa.select(accounts).where(
                accounts.c.client_id == client_id, accounts.c.account_type == "asset", accounts.c.expected_return.isnot(None),
            )).mappings():
                bind.execute(returns.insert().values(scenario_id=goal_id, account_id=account["id"], annual_return=account["expected_return"]))
        else:
            goal_id = goal["id"]
        originals = bind.execute(sa.select(events).where(events.c.client_id == client_id).order_by(events.c.id)).mappings().all()
        for source in originals:
            bind.execute(events.update().where(events.c.id == source["id"]).values(scenario_id=goal_id, lineage=str(uuid4())))
        originals = bind.execute(sa.select(events).where(events.c.client_id == client_id).order_by(events.c.id)).mappings().all()
        original_ids = [row["id"] for row in originals]
        edges = bind.execute(sa.select(links).where(
            links.c.client_id == client_id, links.c.from_event_id.in_(original_ids), links.c.to_event_id.in_(original_ids),
        ).order_by(links.c.id)).mappings().all()
        children = {name: bind.execute(sa.select(tables[name]).where(
            tables[name].c.client_id == client_id, tables[name].c.life_event_id.in_(original_ids),
        ).order_by(tables[name].c.id)).mappings().all() for name in ("life_event_conditions", "milestones")}
        for story in stories:
            if story["id"] == goal_id:
                continue
            event_map, link_map = {}, {}
            for source in originals:
                values = {key: value for key, value in source.items() if key != "id"}
                values["scenario_id"] = story["id"]
                event_map[source["id"]] = bind.execute(events.insert().values(**values)).inserted_primary_key[0]
            for source in edges:
                values = {key: value for key, value in source.items() if key != "id"}
                values.update(from_event_id=event_map[source["from_event_id"]], to_event_id=event_map[source["to_event_id"]])
                link_map[source["id"]] = bind.execute(links.insert().values(**values)).inserted_primary_key[0]
            for name, rows in children.items():
                for source in rows:
                    values = {key: value for key, value in source.items() if key != "id"}
                    values["life_event_id"] = event_map[source["life_event_id"]]
                    if name == "life_event_conditions" and source["metric"] == "goal_progress":
                        values["reference_id"] = event_map.get(source["reference_id"], source["reference_id"])
                    if name == "milestones":
                        values["source_snapshot"] = _remap(source["source_snapshot"], event_map, link_map)
                    bind.execute(tables[name].insert().values(**values))

    op.drop_table("life_scenario_choices")
    with op.batch_alter_table("life_event_links") as batch:
        batch.drop_constraint("ck_life_event_links_kind", type_="check")
        batch.create_check_constraint("ck_life_event_links_kind", "kind = 'after'")
    with op.batch_alter_table("life_events") as batch:
        batch.alter_column("scenario_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("lineage", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_life_events_scenario_id", "life_scenarios", ["scenario_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_life_events_scenario_id", ["scenario_id"])
        batch.create_index("ix_life_events_lineage", ["lineage"])


def downgrade():
    bind = op.get_bind()
    # Only the currently adopted story survives; its capsules keep their IDs and claims.
    # Explicit child deletes also support SQLite batch DDL with FK checks suspended.
    copies = "SELECT id FROM life_events WHERE scenario_id NOT IN (SELECT id FROM life_scenarios WHERE is_goal = true)"
    for table in ("life_event_conditions", "milestones", "simulation_scenarios"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE life_event_id IN ({copies})"))
    bind.execute(sa.text(f"DELETE FROM life_event_links WHERE from_event_id IN ({copies}) OR to_event_id IN ({copies})"))
    bind.execute(sa.text("""
        DELETE FROM life_events WHERE scenario_id NOT IN
            (SELECT id FROM life_scenarios WHERE is_goal = true)
    """))
    with op.batch_alter_table("life_event_links") as batch:
        batch.drop_constraint("ck_life_event_links_kind", type_="check")
        batch.create_check_constraint("ck_life_event_links_kind", "kind IN ('after', 'alternative')")
    op.create_table(
        "life_scenario_choices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("life_event_links.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("scenario_id", "link_id", name="uq_life_scenario_choices_link"),
    )
    with op.batch_alter_table("life_events") as batch:
        batch.drop_index("ix_life_events_lineage")
        batch.drop_index("ix_life_events_scenario_id")
        batch.drop_constraint("fk_life_events_scenario_id", type_="foreignkey")
        batch.drop_column("lineage")
        batch.drop_column("scenario_id")
