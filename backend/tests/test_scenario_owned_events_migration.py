"""Exercise the actual N1a data migration using a restored shared-graph schema."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import op
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import models
from app.services import life_scenario_service as service
from app.services import capsule_service
from test_life_scenarios import db, story, account, earmark, journal_snapshot, node


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261017_0068_scenario_owned_events.py"
    spec = importlib.util.spec_from_file_location("n1a_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shared_schema(connection):
    # SQLite recreates parent tables for ALTER; suspend checks only for this DDL.
    with Operations.context(MigrationContext.configure(connection)):
        with op.batch_alter_table("life_events") as batch:
            batch.drop_index("ix_life_events_lineage")
            batch.drop_index("ix_life_events_scenario_id")
            batch.drop_column("lineage")
            batch.drop_column("scenario_id")
        with op.batch_alter_table("life_event_links") as batch:
            batch.drop_constraint("ck_life_event_links_kind", type_="check")
            batch.create_check_constraint("ck_life_event_links_kind", "kind IN ('after', 'alternative')")
        op.create_table(
            "life_scenario_choices", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False),
            sa.Column("link_id", sa.Integer(), sa.ForeignKey("life_event_links.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("scenario_id", "link_id", name="uq_life_scenario_choices_link"),
        )


def run_ddl(db, action):
    db.commit()
    with db.get_bind().connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            with connection.begin():
                action(connection)
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            connection.commit()
    db.expire_all()


def run_migration(db, method):
    def apply(connection):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration(), method)()
    run_ddl(db, apply)


def test_upgrade_copies_graph_preserves_projection_and_capsules_and_downgrade_keeps_current_goal(db, caplog):
    goal, root, children, edges = story(db)
    account(db, rate=3.5, balance=10000)
    cap = earmark(db, root, claim=600)
    draft = service.create(db, 1, "別案")
    original_id, goal_id, draft_id, cap_id = root.id, goal.id, draft.id, cap.id
    before = service.project(db, 1, goal)["projection"]
    journal = journal_snapshot(db)
    claims = capsule_service.claimed_minor(db, 1, cap_id)
    run_ddl(db, shared_schema)
    run_migration(db, "upgrade")
    originals = db.query(models.LifeEvent).filter_by(scenario_id=goal_id).order_by(models.LifeEvent.id).all()
    copies = db.query(models.LifeEvent).filter_by(scenario_id=draft_id).order_by(models.LifeEvent.id).all()
    assert len(originals) == len(copies) == 3
    assert originals[0].id == original_id
    assert [e.lineage for e in originals] == [e.lineage for e in copies]
    assert len({e.lineage for e in originals}) == 3
    assert db.get(models.Capsule, cap_id).life_event_id == original_id
    assert all(not e.capsules for e in copies)
    assert db.query(models.LifeEventCondition).count() == db.query(models.Milestone).count() == 2
    condition = db.query(models.LifeEventCondition).filter_by(life_event_id=copies[1].id).one()
    assert condition.reference_id == copies[0].id
    for scenario_id in (goal_id, draft_id):
        assert service.project(db, 1, service.get(db, 1, scenario_id))["projection"] == before
    assert "life_scenario_choices" not in sa.inspect(db.get_bind()).get_table_names()
    assert not next(col for col in sa.inspect(db.get_bind()).get_columns("life_events") if col["name"] == "scenario_id")["nullable"]
    service.make_goal(db, 1, draft_id)
    adopted_id = db.get(models.Capsule, cap_id).life_event_id
    assert adopted_id != original_id
    copy_ids = [e.id for e in copies]
    run_migration(db, "downgrade")
    with db.get_bind().connect() as connection:
        assert connection.execute(sa.text("SELECT id FROM life_events ORDER BY id")).scalars().all() == copy_ids
        assert connection.execute(sa.text("SELECT COUNT(*) FROM life_scenario_choices")).scalar() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM milestones")).scalar() == 1
        assert connection.execute(sa.text("SELECT life_event_id FROM capsules WHERE id=:id"), {"id": cap_id}).scalar() == adopted_id
        assert "alternative" in sa.inspect(connection).get_check_constraints("life_event_links")[0]["sqltext"]
        assert not {"lineage", "scenario_id"} & {c["name"] for c in sa.inspect(connection).get_columns("life_events")}
    assert journal_snapshot(db) == journal
    assert capsule_service.claimed_minor(db, 1, cap_id) == claims
    run_migration(db, "upgrade")
    assert service.project(db, 1, service.get_goal(db, 1))["projection"] == before
    assert journal_snapshot(db) == journal


def test_upgrade_seeds_missing_goal_with_defaults_and_converts_alternatives(db, caplog):
    goal, root, _, edges = story(db)
    cash = account(db, rate=3.5)
    account(db, name="未設定", rate=None)
    account(db, name="収入", kind="income", rate=9)
    draft = service.create(db, 1, "旧別案")
    draft_id = draft.id
    client_id, goal_id, cash_id = 1, goal.id, cash.id
    run_ddl(db, shared_schema)
    with db.get_bind().begin() as connection:
        connection.execute(sa.text("DELETE FROM life_scenarios WHERE id=:id"), {"id": goal_id})
        connection.execute(sa.text("UPDATE life_event_links SET kind='alternative'"))
    run_migration(db, "upgrade")
    seeded = service.get_goal(db, client_id)
    assert (seeded.name, seeded.annual_return, seeded.inflation, seeded.horizon_years) == ("基本シナリオ", 5, 2, 30)
    assert service.account_returns(db, seeded) == [{"account_id": cash_id, "annual_return": 3.5}]
    assert len(service.resolve(db, client_id, seeded).events) == 3
    assert [e.lineage for e in db.query(models.LifeEvent).filter_by(scenario_id=draft_id).order_by(models.LifeEvent.id)] == [
        e.lineage for e in db.query(models.LifeEvent).filter_by(scenario_id=seeded.id).order_by(models.LifeEvent.id)]
    assert "Converting alternative" in caplog.text
    assert all(link.kind == "after" for link in db.query(models.LifeEventLink))
    assert service.get_goal(db, 2) is None
