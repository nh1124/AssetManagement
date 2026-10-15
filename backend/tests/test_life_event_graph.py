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
        client_id=client_id, name=name, target_date=target_date,
        target_amount_minor=amount, archived_at=datetime(2026, 1, 1) if archived else None,
    )
    db.add(value)
    db.commit()
    return value


def link(db, source, target, kind="after", offset=0):
    return graph.create_link(
        db, 1, from_event_id=source.id, to_event_id=target.id, kind=kind, offset_months=offset,
    )


def fork(db, name):
    root, a, b = [node(db, f"{name}{suffix}") for suffix in ("", "甲", "乙")]
    edges = [link(db, root, child, "alternative") for child in (a, b)]
    return root, a, b, edges


@pytest.mark.parametrize("with_event", [False, True])
def test_no_links_adopts_the_only_scenario_without_confirmation(db, with_event):
    if with_event:
        node(db, "独立")
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 1
    assert graph.adopted_scenario(db, 1, scenarios) == graph.Adoption(scenarios[0], True)
    assert graph.adopt_scenario(db, 1, "base") == graph.Adoption(scenarios[0], True)


def test_no_enumerated_scenarios_has_no_adoption(db):
    assert graph.adopted_scenario(db, 1, []) == graph.Adoption(None, False)


def test_unadopted_fork_defaults_to_first_scenario_and_needs_confirmation(db):
    fork(db, "住居")
    scenarios = graph.enumerate_scenarios(db, 1)
    assert graph.adopted_scenario(db, 1, scenarios) == graph.Adoption(scenarios[0], False)
    assert all(edge.adopted is False for edge in graph.list_links(db, 1))


def test_adopting_second_branch_survives_a_new_session_and_commits_once(db):
    root, _, _, edges = fork(db, "住居")
    after = link(db, root, node(db, "共通"))
    commits = []
    event.listen(db, "after_commit", lambda _: commits.append(True))
    adoption = graph.adopt_scenario(db, 1, str(edges[1].id))
    assert commits == [True]
    assert adoption.scenario.id == str(edges[1].id) and adoption.exact
    with sessionmaker(bind=db.get_bind())() as reread:
        scenarios = graph.enumerate_scenarios(reread, 1)
        assert graph.adopted_scenario(reread, 1, scenarios) == graph.Adoption(scenarios[1], True)
        assert {edge.id for edge in graph.list_links(reread, 1) if edge.adopted} == {edges[1].id}
        assert reread.get(models.LifeEventLink, after.id).adopted is False


def test_new_fork_completes_existing_choice_with_first_matching_scenario(db):
    _, _, _, edges = fork(db, "住居")
    graph.adopt_scenario(db, 1, str(edges[1].id))
    fork(db, "仕事")
    scenarios = graph.enumerate_scenarios(db, 1)
    adoption = graph.adopted_scenario(db, 1, scenarios)
    assert adoption == graph.Adoption(scenarios[2], False)
    assert edges[1].id in adoption.scenario.chosen_link_ids
    assert {edge.id for edge in graph.list_links(db, 1) if edge.adopted} == {edges[1].id}


@pytest.mark.parametrize("removal", ["link", "event", "database_cascade"])
def test_deleting_adopted_link_shrinks_choice_and_keeps_other_fork(db, removal):
    _, _, child, edges = fork(db, "住居")
    _, _, _, other_edges = fork(db, "仕事")
    chosen = graph.enumerate_scenarios(db, 1)[-1]
    graph.adopt_scenario(db, 1, chosen.id)
    if removal == "link":
        graph.delete_link(db, 1, edges[1].id)
    elif removal == "event":
        assert delete_goal(db, 1, child.id)
    else:
        db.execute(delete(models.LifeEvent).where(models.LifeEvent.id == child.id))
        db.commit()
    remaining = {edge.id for edge in graph.list_links(db, 1) if edge.adopted}
    assert remaining == {other_edges[1].id}
    scenarios = graph.enumerate_scenarios(db, 1)
    adoption = graph.adopted_scenario(db, 1, scenarios)
    assert adoption == graph.Adoption(scenarios[1], False)
    assert remaining.issubset(adoption.scenario.chosen_link_ids)


@pytest.mark.parametrize("invalid", ["unknown", "stale", "foreign"])
def test_unknown_scenario_is_refused_with_422_without_changing_adoption(db, invalid):
    _, _, _, edges = fork(db, "住居")
    graph.adopt_scenario(db, 1, str(edges[0].id))
    scenario_id, client_id = "unknown", 1
    if invalid == "stale":
        scenario_id = str(edges[1].id)
        graph.delete_link(db, 1, edges[1].id)
    elif invalid == "foreign":
        scenario_id, client_id = str(edges[0].id), 2
    with pytest.raises(Refused) as error:
        graph.adopt_scenario(db, client_id, scenario_id)
    assert error.value.status_code == 422
    assert "選び直してください" in str(error.value)
    assert {edge.id for edge in graph.list_links(db, 1) if edge.adopted} == {edges[0].id}


def test_switching_branch_replaces_previous_adoption_and_preserves_other_client(db):
    _, _, _, edges = fork(db, "住居")
    foreign_a, foreign_b = [node(db, name, client_id=2) for name in ("別の始点", "別の終点")]
    foreign = graph.create_link(db, 2, from_event_id=foreign_a.id, to_event_id=foreign_b.id, kind="alternative")
    graph.adopt_scenario(db, 2, str(foreign.id))
    for edge in edges:
        adoption = graph.adopt_scenario(db, 1, str(edge.id))
        assert adoption.exact and adoption.scenario.chosen_link_ids == [edge.id]
        assert {item.id for item in graph.list_links(db, 1) if item.adopted} == {edge.id}
        assert graph.list_links(db, 2)[0].adopted is True


def test_after_links_do_not_contribute_to_adopted_choice(db):
    a, b = node(db, "始点"), node(db, "終点")
    edge = link(db, a, b)
    # Ignore a malformed mark: after links never represent a choice.
    edge.adopted = True
    db.commit()
    scenarios = graph.enumerate_scenarios(db, 1)
    assert graph.adopted_scenario(db, 1, scenarios) == graph.Adoption(scenarios[0], True)


def test_unmatched_adoption_has_no_resolved_scenario(db):
    _, _, child, edges = fork(db, "住居")
    graph.adopt_scenario(db, 1, str(edges[1].id))
    child.archived_at = datetime.utcnow()
    db.commit()
    assert graph.adopted_scenario(db, 1, graph.enumerate_scenarios(db, 1)) == graph.Adoption(None, False)


def test_backup_preserves_adopted_branch_after_link_ids_are_remapped(db):
    fork(db, "住居")
    fork(db, "仕事")
    chosen = graph.enumerate_scenarios(db, 1)[-1]
    graph.adopt_scenario(db, 1, chosen.id)
    document = export_client(db, db.get(models.Client, 1))
    assert {edge["id"] for edge in document["data"]["life_event_links"] if edge["adopted"]} == set(chosen.chosen_link_ids)
    import_client(db, db.get(models.Client, 2), data=document["data"], version=document["version"], manifest=document["manifest"])
    scenarios = graph.enumerate_scenarios(db, 2)
    adoption = graph.adopted_scenario(db, 2, scenarios)
    assert adoption == graph.Adoption(scenarios[-1], True)
    assert adoption.scenario.label == chosen.label
    assert set(adoption.scenario.chosen_link_ids).isdisjoint(chosen.chosen_link_ids)
    assert {edge.id for edge in graph.list_links(db, 2) if edge.adopted} == set(adoption.scenario.chosen_link_ids)


def test_older_backup_defaults_to_no_adopted_links(db):
    fork(db, "住居")
    document = export_client(db, db.get(models.Client, 1))
    for edge in document["data"]["life_event_links"]:
        del edge["adopted"]
    import_client(db, db.get(models.Client, 2), data=document["data"], version=18, manifest=None)
    scenarios = graph.enumerate_scenarios(db, 2)
    assert all(edge.adopted is False for edge in graph.list_links(db, 2))
    assert graph.adopted_scenario(db, 2, scenarios) == graph.Adoption(scenarios[0], False)


def test_after_chain_composes_month_offsets_and_keeps_stored_dates(db):
    a, b, c, d = [node(db, name) for name in "ABCD"]
    link(db, a, b, offset=1)
    link(db, b, c, offset=2)
    link(db, c, d, offset=0)
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 1
    assert [item.resolved_date for item in scenarios[0].events] == [
        date(2030, 1, 31), date(2030, 2, 28), date(2030, 4, 28), date(2030, 1, 31),
    ]
    assert b.target_date == c.target_date == date(2030, 1, 31)
    assert scenarios[0].id == "base"


def test_fork_includes_one_alternative_plus_all_after_children_and_roots(db):
    root, a, b, edges = fork(db, "開業")
    always, independent, leaf = [node(db, name) for name in ("準備", "退職", "子孫")]
    link(db, root, always)
    link(db, a, leaf)
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 2 and scenarios.fork_count == 1
    assert {item.id for item in scenarios[0].events} == {root.id, a.id, always.id, independent.id, leaf.id}
    assert {item.id for item in scenarios[1].events} == {root.id, b.id, always.id, independent.id}
    assert [scenario.id for scenario in scenarios] == [str(edge.id) for edge in edges]
    assert [scenario.label for scenario in scenarios] == [a.name, b.name]
    assert [asdict(item) for item in scenarios] == [asdict(item) for item in graph.enumerate_scenarios(db, 1)]


def test_two_independent_forks_produce_four(db):
    fork(db, "住居")
    fork(db, "仕事")
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 4 and scenarios.fork_count == 2
    assert len({scenario.id for scenario in scenarios}) == 4
    assert all(len(scenario.chosen_link_ids) == 2 for scenario in scenarios)


def test_nested_fork_only_counts_choices_when_reached(db):
    root, a, b, edges = fork(db, "進路")
    c, d = node(db, "進学"), node(db, "留学")
    link(db, a, c, "alternative")
    link(db, a, d, "alternative")
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 3
    assert scenarios[-1].chosen_link_ids == [edges[-1].id]
    assert {item.id for item in scenarios[-1].events} == {root.id, b.id}


def test_cap_is_exact_and_seventh_binary_fork_truncates(db):
    for index in range(6):
        fork(db, str(index))
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 64 and not scenarios.truncated and scenarios.fork_count == 6
    fork(db, "追加")
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 64 and scenarios.truncated and scenarios.fork_count == 7


def test_third_large_fork_stops_at_64(db):
    for name in ("住居", "仕事"):
        fork(db, name)
    root = node(db, "第三分岐")
    for index in range(20):
        link(db, root, node(db, f"選択{index}"), "alternative")
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 64 and scenarios.truncated and scenarios.fork_count == 3


def test_cap_stops_resolving_after_the_first_excess_scenario(db, monkeypatch):
    root = node(db, "起点")
    children = [node(db, str(index)) for index in range(80)]
    for child in children:
        link(db, root, child, "alternative", 12)
    original = graph._offset_date
    calls = []

    def resolve(source, months):
        calls.append((source, months))
        return original(source, months)

    monkeypatch.setattr(graph, "_offset_date", resolve)
    scenarios = graph.enumerate_scenarios(db, 1)
    assert len(scenarios) == 64 and scenarios.truncated
    assert len(calls) == 65


def test_stable_ids_do_not_depend_on_event_names(db):
    _, a, _, _ = fork(db, "住居")
    original = graph.enumerate_scenarios(db, 1)
    a.name = "改名"
    db.commit()
    renamed = graph.enumerate_scenarios(db, 1)
    assert [item.id for item in original] == [item.id for item in renamed]
    assert renamed[0].label == "改名"


def test_missing_source_date_stays_unresolved_and_negative_offsets_are_calendar_months(db):
    a = node(db, "未定", target_date=None)
    b = node(db, "翌月")
    link(db, a, b, offset=1)
    assert [item.resolved_date for item in graph.enumerate_scenarios(db, 1)[0].events] == [None, None]
    assert graph._offset_date(date(2032, 3, 31), -1) == date(2032, 2, 29)
    with pytest.raises(Refused):
        graph._offset_date(date(2030, 1, 1), 120000)


def test_cycle_is_refused_before_writing_and_names_both_events(db):
    a, b, c = [node(db, name) for name in ("開業", "引越", "退職")]
    link(db, a, b)
    link(db, b, c, "alternative")
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
        link(db, a, b, "alternative")
    assert len(graph.list_links(db, 1)) == 1


def test_archived_nodes_and_incident_edges_are_excluded(db):
    a, b = node(db, "A"), node(db, "B")
    link(db, a, b, offset=12)
    a.archived_at = datetime.utcnow()
    node(db, "独立した中止", archived=True)
    node(db, "別人", client_id=2)
    db.commit()
    scenarios = graph.enumerate_scenarios(db, 1)
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
    assert [item.resolved_date for item in graph.enumerate_scenarios(db, 1)[0].events] == [a.target_date, b.target_date]


def test_merge_is_counted_once_resolved_after_sources_and_uses_lowest_active_link(db):
    shared = node(db, "合流")
    a = node(db, "A", target_date=date(2030, 1, 1))
    b = node(db, "B", target_date=date(2040, 1, 1))
    first = link(db, b, shared, offset=12)
    link(db, a, shared, offset=12)
    scenario = graph.enumerate_scenarios(db, 1)[0]
    assert len(scenario.events) == 3
    assert scenario.events[-1].id == shared.id
    assert scenario.events[-1].resolved_date == date(2041, 1, 1)
    assert scenario.events[-1].incoming_link_id == first.id


def test_projection_only_subtracts_resolved_scenario_events_and_shares_demand_math(db, monkeypatch):
    year = date.today().year
    a = node(db, "共通", target_date=date(year, 1, 1), amount=100)
    b = node(db, "来年", target_date=date(year + 10, 1, 1), amount=200)
    c = node(db, "再来年", target_date=date(year + 10, 1, 1), amount=500)
    link(db, a, b, "alternative", 12)
    link(db, a, c, "alternative", 24)
    baseline = [{"year": year + i, "p10": 900, "p50": 1000, "p90": 1100} for i in range(3)]
    calls = []

    def simulate(*args, **kwargs):
        calls.append(kwargs)
        return baseline

    monkeypatch.setattr(graph, "simulate_net_worth_forward", simulate)
    scenarios = graph.enumerate_scenarios(db, 1)
    rows = graph.project_scenario(db, 1, scenarios[0], years=2, annual_return=4, inflation=1)
    assert [row["p50"] for row in rows] == [900, 700, 700]
    assert rows[1]["p10"] == 600 and rows[1]["p90"] == 800
    assert calls == [{"years": 2, "annual_return": 4, "inflation": 1}]
    assert [row["cumulative_target"] for row in aggregate_life_event_demand_by_year(db, 1, 2)] == [100, 100, 100]
    result = graph.compare_scenarios(db, 1, years=2, annual_return=4, inflation=1)
    assert len(calls) == 2
    assert [row["p50"] for row in result["scenarios"][1]["projection"]] == [900, 900, 400]
    assert baseline[0]["p50"] == 1000


def test_backup_carries_links_restore_remaps_both_ends_and_keeps_other_client(db):
    a, b = node(db, "A"), node(db, "B")
    edge = link(db, a, b, "alternative", 18)
    edge.note = "判断"
    db.commit()
    source, target = db.get(models.Client, 1), db.get(models.Client, 2)
    backup = export_client(db, source)
    assert backup["version"] == EXPORT_VERSION == 19
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


def test_http_routes_are_client_scoped_validate_parameters_and_return_cap_metadata(db):
    from fastapi import FastAPI
    from app.routers.life_events import router
    from app.domain.errors import DomainError, detail_for, status_for
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})

    a, b, c = [node(db, name) for name in "ABC"]

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            payload = {"from_event_id": a.id, "to_event_id": b.id, "kind": "alternative", "offset_months": 1}
            response = await client.post("/life-events/links", json=payload)
            assert response.status_code == 200
            edge_id = response.json()["id"]
            assert (await client.get("/life-events/links")).json()[0]["id"] == edge_id
            assert (await client.post("/life-events/links", json={**payload, "to_event_id": c.id})).status_code == 200
            result = (await client.get("/life-events/scenarios?years=2&annual_return=0&inflation=0")).json()
            assert result["fork_count"] == 1 and result["truncated"] is False
            assert len(result["scenarios"]) == 2
            assert len(result["scenarios"][0]["projection"]) == 3
            assert "resolved_date" in result["scenarios"][0]["events"][0]
            assert result["adopted"] == {"scenario_id": result["scenarios"][0]["id"], "exact": False}
            chosen_id = result["scenarios"][1]["id"]
            adopted = await client.post("/life-events/scenarios/adopt", json={"scenario_id": chosen_id})
            assert adopted.status_code == 200
            assert adopted.json() == {"scenario_id": chosen_id, "exact": True}
            reread = (await client.get("/life-events/scenarios?years=2")).json()
            assert reread["adopted"] == adopted.json()
            assert (await client.post("/life-events/scenarios/adopt", json={"scenario_id": "unknown"})).status_code == 422
            assert (await client.post("/life-events/scenarios/adopt", json={})).status_code == 422
            assert (await client.get("/life-events/scenarios?years=0")).status_code == 422
            assert (await client.post("/life-events/links", json={**payload, "kind": "bad"})).status_code == 422
            assert (await client.delete(f"/life-events/links/{edge_id}")).status_code == 200
            app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 2)
            assert (await client.post("/life-events/scenarios/adopt", json={"scenario_id": chosen_id})).status_code == 422
            empty = (await client.get("/life-events/scenarios?years=2")).json()
            assert empty["adopted"] == {"scenario_id": "base", "exact": True}
            assert (await client.get("/life-events/links")).json() == []
            assert (await client.post("/life-events/links", json=payload)).status_code == 404

    async def run_with_wakeups():
        pending = asyncio.create_task(exercise())
        # Sync HTTP handlers need timer wakeups in this sandbox's selector.
        deadline = asyncio.get_running_loop().time() + 30
        while not pending.done() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        if not pending.done():
            pending.cancel()
            pytest.fail("HTTP graph exercise exceeded 30 seconds")
        await pending

    asyncio.run(run_with_wakeups())
