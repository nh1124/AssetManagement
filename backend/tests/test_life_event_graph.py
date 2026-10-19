"""Exercise graph choices, resolved demand and portable edges on scratch data."""
import asyncio
from dataclasses import asdict
from datetime import date, datetime

import httpx
import pytest
from sqlalchemy import create_engine, delete, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, Invalid, NotFound, Refused
from app.domain.transfer import EXPORT_VERSION, validate_import_payload
from app.services import life_event_graph as graph
from app.services import life_scenario_service as saved, life_event_walk as walk
from scenario_fixtures import goal_scenario_id
from app.services.data_transfer_service import export_client, import_client
from app.services.goal_service import delete_goal
from app.services.strategy_service import aggregate_life_event_demand_by_year





@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add_all([
            models.Client(id=1, name="本人", general_settings={"currency": "JPY"}),
            models.Client(id=2, name="別人", general_settings={"currency": "USD"}),
        ])
        session.commit()
        yield session
    engine.dispose()


def node(db, name, *, target_date=date(2030, 1, 31), amount=0, client_id=1, archived=False):
    value = models.LifeEvent(
        scenario_id=goal_scenario_id(db, client_id), client_id=client_id, name=name, target_date=target_date,
        target_amount_minor=amount, archived_at=datetime(2026, 1, 1) if archived else None,
    )
    db.add(value)
    db.commit()
    return value


def link(db, source, target, kind="after", offset=0):
    return graph.create_link(
        db, 1, from_event_id=source.id, to_event_id=target.id, kind=kind, offset_months=offset,
    )


def test_after_chain_composes_month_offsets_and_keeps_stored_dates(db):
    a, b, c, d = [node(db, name) for name in "ABCD"]
    link(db, a, b, offset=1)
    link(db, b, c, offset=2)
    link(db, c, d, offset=0)
    scenarios = [saved.resolve(db, 1, saved.get_goal(db, 1))]
    assert len(scenarios) == 1
    assert [item.resolved_date for item in scenarios[0].events] == [
        date(2030, 1, 31), date(2030, 2, 28), date(2030, 4, 28), date(2030, 1, 31),
    ]
    assert b.target_date == c.target_date == date(2030, 1, 31)


def test_missing_source_date_stays_unresolved_and_negative_offsets_are_calendar_months(db):
    a = node(db, "未定", target_date=None)
    b = node(db, "翌月")
    link(db, a, b, offset=1)
    assert [item.resolved_date for item in saved.resolve(db, 1, saved.get_goal(db, 1)).events] == [None, None]
    assert walk._offset_date(date(2032, 3, 31), -1) == date(2032, 2, 29)
    with pytest.raises(Refused):
        walk._offset_date(date(2030, 1, 1), 120000)


def test_cycle_is_refused_before_writing_and_names_both_events(db):
    a, b, c = [node(db, name) for name in ("開業", "引越", "退職")]
    link(db, a, b)
    link(db, b, c, "after")
    with pytest.raises(Refused) as error:
        link(db, c, a)
    assert a.name in str(error.value) and c.name in str(error.value)
    assert len(graph.list_links(db, 1)) == 2
    assert not db.new


@pytest.mark.parametrize("which", ["source", "target"])
@pytest.mark.parametrize("invalid", ["foreign", "archived", "missing"])
def test_both_ends_must_belong_to_client_and_be_active(db, which, invalid):
    a, b = node(db, "始点"), node(db, "終点")
    bad = a if which == "source" else b
    if invalid == "foreign":
        bad.client_id = 2
    elif invalid == "archived":
        bad.archived_at = datetime.utcnow()
    else:
        db.delete(bad)
    db.commit()
    with pytest.raises((NotFound, Refused)):
        graph.create_link(db, 1, from_event_id=a.id, to_event_id=b.id, kind="after")
    assert not graph.list_links(db, 1)


def test_self_duplicate_and_invalid_kind_are_refused(db):
    a, b = node(db, "A"), node(db, "B")
    with pytest.raises(Refused):
        link(db, a, a)
    with pytest.raises(Refused):
        link(db, a, b, "unknown")
    link(db, a, b)
    with pytest.raises(Conflict):
        link(db, a, b, "after")
    assert len(graph.list_links(db, 1)) == 1


def test_archived_nodes_and_incident_edges_are_excluded(db):
    a, b = node(db, "A"), node(db, "B")
    link(db, a, b, offset=12)
    a.archived_at = datetime.utcnow()
    node(db, "独立した中止", archived=True)
    node(db, "別人", client_id=2)
    db.commit()
    scenarios = [saved.resolve(db, 1, saved.get_goal(db, 1))]
    assert [item.id for item in scenarios[0].events] == [b.id]
    assert scenarios[0].events[0].incoming_link_id is None
    assert scenarios[0].events[0].resolved_date == b.target_date
    assert len(graph.list_links(db, 1)) == 1


@pytest.mark.parametrize("end", ["source", "target"])
def test_deleting_either_event_removes_links(db, end):
    a, b = node(db, "A"), node(db, "B")
    link(db, a, b)
    assert delete_goal(db, 1, a.id if end == "source" else b.id)
    assert not graph.list_links(db, 1)


@pytest.mark.parametrize("end", ["source", "target"])
def test_database_foreign_keys_cascade_on_both_ends(db, end):
    a, b = node(db, "A"), node(db, "B")
    link(db, a, b)
    db.execute(delete(models.LifeEvent).where(models.LifeEvent.id == (a.id if end == "source" else b.id)))
    db.commit()
    assert not graph.list_links(db, 1)


def test_database_enforces_kind_and_unique_pair(db):
    a, b = node(db, "A"), node(db, "B")
    link(db, a, b)
    for kind, source, target in [("bad", b.id, a.id), ("alternative", a.id, b.id)]:
        with pytest.raises(IntegrityError):
            db.add(models.LifeEventLink(client_id=1, from_event_id=source, to_event_id=target, kind=kind))
            db.flush()
        db.rollback()
    assert len(graph.list_links(db, 1)) == 1


def test_deleting_link_is_client_scoped_and_restores_root(db):
    a, b = node(db, "A"), node(db, "B")
    edge = link(db, a, b, offset=12)
    with pytest.raises(NotFound):
        graph.delete_link(db, 2, edge.id)
    assert graph.list_links(db, 2) == []
    graph.delete_link(db, 1, edge.id)
    assert not graph.list_links(db, 1)
    assert [item.resolved_date for item in saved.resolve(db, 1, saved.get_goal(db, 1)).events] == [a.target_date, b.target_date]


def test_merge_is_counted_once_resolved_after_sources_and_uses_lowest_active_link(db):
    shared = node(db, "合流")
    a = node(db, "A", target_date=date(2030, 1, 1))
    b = node(db, "B", target_date=date(2040, 1, 1))
    first = link(db, b, shared, offset=12)
    link(db, a, shared, offset=12)
    scenario = saved.resolve(db, 1, saved.get_goal(db, 1))
    assert len(scenario.events) == 3
    assert scenario.events[-1].id == shared.id
    assert scenario.events[-1].resolved_date == date(2041, 1, 1)
    assert scenario.events[-1].incoming_link_id == first.id


def test_backup_carries_links_restore_remaps_both_ends_and_keeps_other_client(db):
    a, b = node(db, "A"), node(db, "B")
    edge = link(db, a, b, "after", 18)
    edge.note = "判断"
    db.commit()
    source, target = db.get(models.Client, 1), db.get(models.Client, 2)
    backup = export_client(db, source)
    assert backup["version"] == EXPORT_VERSION == 25
    assert backup["data"]["life_event_links"][0]["note"] == "判断"
    import_client(db, target, data=backup["data"], version=backup["version"], manifest=backup["manifest"])
    restored = graph.list_links(db, 2)[0]
    assert restored.from_event_id != a.id and restored.to_event_id != b.id
    assert db.get(models.LifeEvent, restored.from_event_id).name == "A"
    assert db.get(models.LifeEvent, restored.to_event_id).name == "B"
    assert db.get(models.LifeEvent, restored.to_event_id).client_id == 2
    assert (restored.kind, restored.offset_months, restored.note, restored.created_at) == (
        edge.kind, edge.offset_months, edge.note, edge.created_at,
    )
    assert len(graph.list_links(db, 1)) == 1
    # A second replace clears old links before deleting their events.
    import_client(db, target, data=backup["data"], version=backup["version"], manifest=backup["manifest"])
    assert len(graph.list_links(db, 2)) == 1


@pytest.mark.parametrize("defect", ["cycle", "missing", "self", "duplicate", "kind", "offset"])
def test_restore_rejects_invalid_graph_before_replacing_any_data(db, defect):
    a, b = node(db, "A"), node(db, "B")
    link(db, a, b)
    backup = export_client(db, db.get(models.Client, 1))
    data = backup["data"]
    edge = data["life_event_links"][0]
    if defect == "cycle":
        data["life_event_links"].append({**edge, "id": 100, "from_event_id": b.id, "to_event_id": a.id})
    elif defect == "missing":
        edge["to_event_id"] = 999
    elif defect == "self":
        edge["to_event_id"] = a.id
    elif defect == "duplicate":
        data["life_event_links"].append({**edge, "id": 100})
    elif defect == "kind":
        edge["kind"] = "bad"
    else:
        edge["offset_months"] = 1.5
    assert validate_import_payload(data, 16)["error_count"]
    with pytest.raises(Invalid):
        import_client(db, db.get(models.Client, 1), data=data, version=16, manifest=None)
    assert len(graph.list_links(db, 1)) == 1
    assert db.query(models.LifeEvent).count() == 2
