"""Scenario-owned stories keep simulations independent and earmarks on the goal."""
import asyncio
from datetime import date, datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, delete, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from scenario_fixtures import goal_scenario_id
from app.services import capsule_service, goal_service
from app.workflows.goal_workflow import create_goal
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, Invalid, NotFound, Refused, detail_for, status_for
from app.domain.transfer import EXPORT_VERSION, validate_import_payload, _sha256
from app.routers.life_scenarios import router
from app.routers.life_events import router as events_router
from app.services import life_scenario_service as service, life_event_graph as graph
from app.services.data_transfer_service import export_client, import_client
from app.services.account_return_service import blended_return
from app.services.ledger_service import create_account, create_transaction




@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=1, name="本人", general_settings={"currency": "JPY"}),
                         models.Client(id=2, name="別人", general_settings={"currency": "JPY"}),
                         models.Client(id=3, name="空", general_settings={"currency": "JPY"})])
        session.commit()
        yield session
    engine.dispose()


def account(db, name="口座", client_id=1, kind="asset", balance=0):
    row = create_account(db, client_id, {"name": name, "account_type": kind})
    if balance:
        income = create_account(db, client_id, {"name": name + "給与", "account_type": "income"})
        create_transaction(db, client_id=client_id, date=date(2020, 1, 1), description="開始残高",
                           amount_minor=balance, currency="JPY", from_account_id=income.id, to_account_id=row.id)
        db.commit()
    return row


def config(db, **values):
    row = models.SimulationConfig(client_id=1, **{"annual_return": 7.5, "inflation_rate": 1.5,
        "horizon_years": 8, "monthly_savings_minor": 50000, "tax_rate": 20, "volatility": 15, **values})
    db.add(row)
    db.commit()
    return row




@pytest.mark.parametrize("invalid", ["income", "expense", "liability", "foreign", "missing", "duplicate", "nan"])
def test_account_returns_validate_before_replacing(db, invalid):
    row = account(db)
    scenario = service.create(db, 1, "保存")
    service.replace_account_returns(db, 1, scenario.id, [{"account_id": row.id, "annual_return": 3}])
    if invalid in {"income", "expense", "liability"}:
        bad_id = account(db, name=invalid, kind=invalid).id
    elif invalid == "foreign":
        bad_id = account(db, client_id=2).id
    else:
        bad_id = row.id if invalid in {"duplicate", "nan"} else 99999
    returns = [{"account_id": bad_id, "annual_return": float("nan") if invalid == "nan" else 2}]
    if invalid == "duplicate":
        returns *= 2
    with pytest.raises(Refused):
        service.replace_account_returns(db, 1, scenario.id, returns)
    assert service.account_returns(db, scenario) == [{"account_id": row.id, "annual_return": 3}]


def test_goal_switch_commits_once_and_goal_delete_is_refused(db):
    first, second = [service.create(db, 1, name) for name in ("第一", "第二")]
    service.make_goal(db, 1, first.id)
    commits = []
    event.listen(db, "after_commit", lambda _: commits.append(True))
    service.make_goal(db, 1, second.id)
    assert commits == [True]
    assert first.is_goal is False and second.is_goal is True
    assert db.query(models.LifeScenario).filter_by(client_id=1, is_goal=True).count() == 1
    with pytest.raises(Refused, match="ゴールのシナリオは削除できません") as error:
        service.delete(db, 1, second.id)
    assert error.value.status_code == 422
    service.delete(db, 1, first.id)
    with pytest.raises(NotFound):
        service.get(db, 2, second.id)


def test_database_enforces_goal_uniqueness_per_client_and_horizon(db):
    first = service.create(db, 1, "第一")
    service.make_goal(db, 1, first.id)
    other = service.create(db, 2, "第一")
    service.make_goal(db, 2, other.id)
    for values in ({"is_goal": True}, {"horizon_years": 0}, {"horizon_years": 61}):
        with pytest.raises(IntegrityError):
            db.add(models.LifeScenario(client_id=1, name="不正", **values))
            db.flush()
        db.rollback()


def test_defaults_do_not_use_config_or_account_rates_for_new_scenarios_without_goal(db):
    config(db)
    account(db)
    scenario = service.create(db, 1, "  新規  ")
    assert scenario.name == "新規"
    assert (scenario.annual_return, scenario.inflation, scenario.horizon_years) == (5, 2, 30)
    assert service.account_returns(db, scenario) == []
    with pytest.raises(Conflict):
        service.create(db, 1, "新規")
    for name in ("", "  "):
        with pytest.raises(Refused):
            service.create(db, 1, name)
    assert service.create(db, 2, "新規").name == "新規"


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(router)
    app.include_router(events_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    return app


def request(app, method, url, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.request(method, url, **kwargs))
            # Timers wake the sandbox selector for sync HTTP handlers.
            for _ in range(3000):
                if pending.done():
                    return await pending
                await asyncio.sleep(.01)
            pending.cancel()
            pytest.fail("HTTP scenario request timed out")
    return asyncio.run(run())


@pytest.mark.parametrize("patch", [{"name": " "}, {"annual_return": "nan"}, {"annual_return": None},
    {"inflation": "Infinity"}, {"horizon_years": 0}, {"horizon_years": 61}, {"horizon_years": 1.5}, {"horizon_years": None}])
def test_http_rejects_invalid_assumptions_in_japanese(db, api, patch):
    scenario = service.create(db, 1, "保存")
    response = request(api, "PUT", f"/life-scenarios/{scenario.id}", json=patch)
    assert response.status_code == 422
    assert any("指定してください" in row["msg"] or "入力してください" in row["msg"] for row in response.json()["detail"])


def test_deprecated_scenario_routes_are_absent(api):
    paths = api.openapi()["paths"]
    assert "/life-events/scenarios" not in paths
    assert "/life-events/scenarios/adopt" not in paths
    # The remaining /{event_id} routes match this path but provide no GET handler.
    assert request(api, "GET", "/life-events/scenarios").status_code == 405
    assert request(api, "POST", "/life-events/scenarios/adopt", json={"scenario_id": "base"}).status_code == 404


def node(db, name="予定", client_id=1, **kwargs):
    scenario_id = kwargs.pop("scenario_id", None)
    if scenario_id is None:
        scenario_id = goal_scenario_id(db, client_id)
    row = models.LifeEvent(client_id=client_id, scenario_id=scenario_id, name=name,
                           target_date=kwargs.pop("target_date", date(date.today().year + 1, 1, 31)),
                           target_amount_minor=kwargs.pop("amount", 0), **kwargs)
    db.add(row)
    db.commit()
    return row


def fork(db, name="進路", source=None, client_id=1):
    source = source or node(db, name, client_id=client_id)
    children = [node(db, name + suffix, client_id=client_id, scenario_id=source.scenario_id) for suffix in ("甲", "乙")]
    edges = [graph.create_link(db, client_id, from_event_id=source.id, to_event_id=child.id,
                               kind="after", offset_months=1) for child in children]
    return source, children, edges


def story(db):
    root, children, edges = fork(db)
    # Include a condition referring to another copied event and a JSON plan snapshot.
    db.add_all([
        models.LifeEventCondition(client_id=1, life_event_id=children[0].id, metric="goal_progress",
                                  comparator="gte", threshold_number=50, reference_id=root.id),
        models.Milestone(client_id=1, life_event_id=children[0].id, date=date(2030, 1, 1),
                         target_amount_minor=123, note="checkpoint", source="simulation", is_active_plan=False,
                         source_snapshot={"nested": [{"life_event_id": root.id, "link_id": edges[0].id}]}),
    ])
    db.commit()
    return service.get_goal(db, 1), root, children, edges


def earmark(db, owner, name="取り置き", claim=0):
    cap = capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name=name, life_event_id=owner.id, target_amount=1000, monthly_contribution=0))
    if claim:
        cash = account(db, name=f"{name}口座", balance=claim)
        entry = db.query(models.JournalEntry).filter_by(account_id=cash.id).one()
        entry.capsule_id = cap.id
        db.commit()
    return cap


def journal_snapshot(db):
    return [tuple(getattr(row, col.name) for col in models.JournalEntry.__table__.columns)
            for row in db.query(models.JournalEntry).order_by(models.JournalEntry.id)]


def test_duplicate_copies_whole_story_and_create_is_empty(db):
    original, root, children, edges = story(db)
    cash = account(db)
    service.update(db, 1, original.id, {"annual_return": 8, "inflation": 1, "horizon_years": 11})
    service.replace_account_returns(db, 1, original.id, [{"account_id": cash.id, "annual_return": 4}])
    cap = earmark(db, root, claim=700)
    claims = capsule_service.claimed_minor(db, 1, cap.id)
    original_projection = service.project(db, 1, original)["projection"]
    empty = service.create(db, 1, "空")
    commits = []
    event.listen(db, "after_commit", lambda _: commits.append(True))
    clone = service.duplicate(db, 1, original.id, "複製")
    assert commits == [True]
    for item in (empty, clone):
        assert (item.annual_return, item.inflation, item.horizon_years, item.is_goal) == (8, 1, 11, False)
        assert service.account_returns(db, item) == service.account_returns(db, original)
    assert service.resolve(db, 1, empty).events == []
    originals = db.query(models.LifeEvent).filter_by(scenario_id=original.id).order_by(models.LifeEvent.id).all()
    copies = db.query(models.LifeEvent).filter_by(scenario_id=clone.id).order_by(models.LifeEvent.id).all()
    assert len(copies) == 3
    assert {e.id for e in originals}.isdisjoint(e.id for e in copies)
    assert [e.lineage for e in originals] == [e.lineage for e in copies]
    for before, after in zip(originals, copies):
        assert {c.name: getattr(before, c.name) for c in models.LifeEvent.__table__.columns if c.name not in {"id", "scenario_id"}} == {
            c.name: getattr(after, c.name) for c in models.LifeEvent.__table__.columns if c.name not in {"id", "scenario_id"}}
    copied_edges = db.query(models.LifeEventLink).filter(models.LifeEventLink.from_event_id == copies[0].id).order_by(models.LifeEventLink.id).all()
    assert [e.to_event_id for e in copied_edges] == [e.id for e in copies[1:]]
    condition = db.query(models.LifeEventCondition).filter_by(life_event_id=copies[1].id).one()
    assert condition.reference_id == copies[0].id
    milestone = db.query(models.Milestone).filter_by(life_event_id=copies[1].id).one()
    assert (milestone.note, milestone.target_amount_minor, milestone.source, milestone.is_active_plan) == ("checkpoint", 123, "simulation", False)
    assert milestone.source_snapshot == {"nested": [{"life_event_id": copies[0].id, "link_id": copied_edges[0].id}]}
    assert all(e.capsules == [] for e in copies)
    assert cap.life_event_id == root.id and capsule_service.claimed_minor(db, 1, cap.id) == claims
    assert service.project(db, 1, original)["projection"] == service.project(db, 1, clone)["projection"] == original_projection
    goal_service.update_goal(db, 1, copies[0].id, schemas.LifeEventUpdate(name="変更", target_amount=900))
    assert db.get(models.LifeEvent, root.id).name == root.name == "進路"
    assert db.get(models.LifeEvent, root.id).target_amount_minor == 0


def test_goal_switch_moves_all_capsules_by_lineage_in_one_commit(db):
    original, root, children, _ = story(db)
    caps = [earmark(db, root, "A", 500), earmark(db, children[0], "B", 600), earmark(db, root, "C")]
    clone = service.duplicate(db, 1, original.id, "複製")
    before = journal_snapshot(db)
    claims = {cap.id: capsule_service.claimed_minor(db, 1, cap.id) for cap in caps}
    expected = {cap.id: db.get(models.LifeEvent, cap.life_event_id).lineage for cap in caps}
    # Loaded relationship collections must not cause orphan deletion during reassignment.
    assert len(root.capsules) == 2
    commits = []
    event.listen(db, "after_commit", lambda _: commits.append(True))
    service.make_goal(db, 1, clone.id)
    assert commits == [True]
    for cap in caps:
        target = db.get(models.LifeEvent, cap.life_event_id)
        assert target.scenario_id == clone.id and target.lineage == expected[cap.id]
        assert capsule_service.claimed_minor(db, 1, cap.id) == claims[cap.id]
    assert journal_snapshot(db) == before
    assert not original.is_goal and clone.is_goal


def test_missing_lineage_conflict_changes_nothing_then_confirmation_detaches(db, api):
    original, root, children, _ = story(db)
    moving = earmark(db, root, "残る", 400)
    missing = earmark(db, children[0], "解除される", 300)
    clone = service.duplicate(db, 1, original.id, "別案")
    copied = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=children[0].lineage).one()
    db.delete(copied)
    db.commit()
    before = journal_snapshot(db)
    prior_links = (moving.life_event_id, missing.life_event_id)
    claims = capsule_service.claimed_minor(db, 1, missing.id)
    commits = []
    event.listen(db, "after_commit", lambda _: commits.append(True))
    response = request(api, "POST", f"/life-scenarios/{clone.id}/goal", json={})
    assert response.status_code == 409
    assert response.json()["detail"] == {"detach": [{"capsule_id": missing.id, "capsule_name": missing.name, "event_name": children[0].name}]}
    assert commits == []
    assert (moving.life_event_id, missing.life_event_id) == prior_links
    assert service.get_goal(db, 1).id == original.id
    assert journal_snapshot(db) == before
    response = request(api, "POST", f"/life-scenarios/{clone.id}/goal", json={"confirm_detach": True})
    assert response.status_code == 200 and response.json()["is_goal"] is True
    # The switch commits once; the adopted goal's baseline follows in its own commit.
    assert commits == [True, True]
    assert db.query(models.GoalBaseline).filter_by(client_id=1, is_current=True).one().scenario_id == clone.id
    assert missing.life_event_id is None
    assert db.get(models.LifeEvent, moving.life_event_id).scenario_id == clone.id
    assert capsule_service.claimed_minor(db, 1, missing.id) == claims
    assert journal_snapshot(db) == before


def test_goal_switch_rolls_back_links_and_flags_on_commit_failure(db, monkeypatch):
    original, root, _, _ = story(db)
    cap = earmark(db, root, claim=700)
    clone = service.duplicate(db, 1, original.id, "複製")
    before = journal_snapshot(db)
    original_id, root_id, cap_id = original.id, root.id, cap.id
    def fail():
        db.flush()
        raise RuntimeError("commit failed")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError, match="commit failed"):
        service.make_goal(db, 1, clone.id)
    assert service.get_goal(db, 1).id == original_id
    assert db.get(models.Capsule, cap_id).life_event_id == root_id
    assert journal_snapshot(db) == before


def test_capsules_can_only_attach_to_goal_events(db):
    original, root, _, _ = story(db)
    cap = earmark(db, root)
    clone = service.duplicate(db, 1, original.id, "複製")
    target = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=root.lineage).one()
    message = "取り置きはゴールのシナリオのライフイベントにだけ紐づけられます。"
    for operation in (
        lambda: capsule_service.update_capsule(db, 1, cap.id, schemas.CapsuleUpdate(life_event_id=target.id)),
        lambda: capsule_service.create_capsule_for_goal(db, 1, target),
        lambda: capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="不正", life_event_id=target.id, target_amount=0, monthly_contribution=0)),
    ):
        with pytest.raises(Refused, match=message):
            operation()
    assert cap.life_event_id == root.id


def test_deleting_draft_cascades_events_and_never_affects_capsules(db):
    original, root, _, _ = story(db)
    cap = earmark(db, root, claim=500)
    clone = service.duplicate(db, 1, original.id, "複製")
    event_ids = [e.id for e in db.query(models.LifeEvent).filter_by(scenario_id=clone.id)]
    before = journal_snapshot(db)
    claim = capsule_service.claimed_minor(db, 1, cap.id)
    service.delete(db, 1, clone.id)
    assert not db.query(models.LifeEvent).filter(models.LifeEvent.id.in_(event_ids)).count()
    assert not db.query(models.LifeEventCondition).filter(models.LifeEventCondition.life_event_id.in_(event_ids)).count()
    assert not db.query(models.Milestone).filter(models.Milestone.life_event_id.in_(event_ids)).count()
    assert db.get(models.Capsule, cap.id).life_event_id == root.id
    assert capsule_service.claimed_minor(db, 1, cap.id) == claim
    assert journal_snapshot(db) == before


def test_event_creation_requires_owned_scenario_and_updates_cannot_move(db, api):
    goal = service.create(db, 1, "本案")
    service.make_goal(db, 1, goal.id)
    draft = service.create(db, 1, "別案")
    foreign = service.create(db, 2, "外部")
    payload = {"name": "新規", "target_date": "2030-01-01", "target_amount": 100}
    assert request(api, "POST", "/life-events/", json=payload).status_code == 422
    assert request(api, "POST", "/life-events/", json={**payload, "scenario_id": foreign.id}).status_code == 404
    made = request(api, "POST", "/life-events/", json={**payload, "scenario_id": draft.id})
    assert made.status_code == 200
    owner = made.json()
    assert owner["scenario_id"] == draft.id and len(owner["lineage"]) == 36
    assert db.query(models.Capsule).count() == 0
    assert request(api, "PUT", f'/life-events/{owner["id"]}', json={"scenario_id": goal.id}).status_code == 422
    assert request(api, "PUT", f'/life-events/{owner["id"]}', json={"lineage": "other"}).status_code == 422
    made_goal = request(api, "POST", "/life-events/", json={**payload, "scenario_id": goal.id})
    assert made_goal.status_code == 200
    assert made_goal.json()["lineage"] != owner["lineage"]
    assert db.query(models.Capsule).one().life_event_id == made_goal.json()["id"]


@pytest.mark.parametrize("suffix", ["/", "/with-progress"])
def test_event_lists_default_to_goal_and_validate_explicit_scenario(db, api, suffix):
    original, root, _, _ = story(db)
    clone = service.duplicate(db, 1, original.id, "複製")
    foreign = service.create(db, 2, "外部")
    expected = {e.id for e in db.query(models.LifeEvent).filter_by(scenario_id=original.id)}
    copies = {e.id for e in db.query(models.LifeEvent).filter_by(scenario_id=clone.id)}
    assert {row["id"] for row in request(api, "GET", "/life-events" + suffix).json()} == expected
    response = request(api, "GET", f"/life-events{suffix}?scenario_id={clone.id}")
    assert response.status_code == 200 and {row["id"] for row in response.json()} == copies
    assert request(api, "GET", f"/life-events{suffix}?scenario_id={foreign.id}").status_code == 404
    assert request(api, "GET", f"/life-events{suffix}?scenario_id=99999").status_code == 404
    assert "choices" not in service.describe(db, 1, clone)
    assert "missing_forks" not in service.describe(db, 1, clone)
    assert request(api, "PUT", f"/life-scenarios/{clone.id}/choices", json={"link_ids": []}).status_code == 404


def test_v22_roundtrip_preserves_independent_graphs_and_remaps_scenario_ids(db):
    original, root, _, _ = story(db)
    cash = account(db, balance=10000)
    service.replace_account_returns(db, 1, original.id, [{"account_id": cash.id, "annual_return": 7}])
    cap = earmark(db, root, claim=500)
    clone = service.duplicate(db, 1, original.id, "複製")
    copied = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=root.lineage).one()
    copied.target_amount_minor = 200
    db.commit()
    document = export_client(db, db.get(models.Client, 1))
    assert document["version"] == EXPORT_VERSION == 25
    assert "life_scenario_choices" not in document["data"]
    projections = {s.name: service.project(db, 1, s)["projection"] for s in (original, clone)}
    for _ in range(2):
        import_client(db, db.get(models.Client, 2), data=document["data"], version=22, manifest=document["manifest"])
        stories = db.query(models.LifeScenario).filter_by(client_id=2).all()
        assert len(stories) == 2
        restored_capsules = db.query(models.Capsule).filter_by(client_id=2).all()
        assert len(restored_capsules) == len(document["data"]["capsules"]) == 1
        assert restored_capsules[0].capsule_type == cap.capsule_type == "manual"
        for restored in stories:
            assert restored.id not in {original.id, clone.id}
            assert service.project(db, 2, restored)["projection"] == projections[restored.name]
        goal = service.get_goal(db, 2)
        assert all(e.scenario_id == goal.id for cap in db.query(models.Capsule).filter_by(client_id=2) if cap.life_event_id for e in [db.get(models.LifeEvent, cap.life_event_id)])
        assert {e.lineage for e in db.query(models.LifeEvent).filter_by(client_id=2)} == {e.lineage for e in db.query(models.LifeEvent).filter_by(client_id=1)}
    assert db.get(models.Capsule, cap.id).life_event_id == root.id


def test_v21_import_assigns_shared_graph_to_goal_and_copies_for_every_draft(db, caplog):
    original, root, _, _ = story(db)
    account(db, balance=10000)
    cap = earmark(db, root, claim=600)
    other = service.create(db, 1, "旧別案")
    before = service.project(db, 1, original)["projection"]
    document = export_client(db, db.get(models.Client, 1))
    data = document["data"]
    for row in data["life_events"]:
        row.pop("scenario_id")
        row.pop("lineage")
    data["life_event_links"][0]["kind"] = "alternative"
    data["life_scenario_choices"] = [{"id": 1, "scenario_id": other.id, "link_id": data["life_event_links"][0]["id"]}]
    checksums = {key: _sha256(rows) for key, rows in data.items()}
    legacy_manifest = {"counts": {key: len(rows) for key, rows in data.items()}, "checksums": checksums,
                       "payload_checksum": _sha256({"data": data, "checksums": checksums})}
    assert [issue["code"] for issue in validate_import_payload(data, 21, legacy_manifest)["issues"]] == ["older_version"]
    import_client(db, db.get(models.Client, 2), data=data, version=21, manifest=legacy_manifest)
    goal = service.get_goal(db, 2)
    draft = db.query(models.LifeScenario).filter_by(client_id=2, is_goal=False).one()
    goal_events = db.query(models.LifeEvent).filter_by(scenario_id=goal.id).order_by(models.LifeEvent.id).all()
    draft_events = db.query(models.LifeEvent).filter_by(scenario_id=draft.id).order_by(models.LifeEvent.id).all()
    assert len(goal_events) == len(draft_events) == 3
    assert [e.lineage for e in goal_events] == [e.lineage for e in draft_events]
    assert all(not e.capsules for e in draft_events)
    assert db.query(models.Capsule).filter_by(client_id=2).count() == len(data["capsules"]) == 1
    assert len(db.query(models.LifeEventCondition).filter_by(client_id=2).all()) == 2
    assert len(db.query(models.Milestone).filter_by(client_id=2).all()) == 2
    assert service.project(db, 2, goal)["projection"] == service.project(db, 2, draft)["projection"] == before
    assert "Converting restored alternative" in caplog.text
    assert all(e.kind == "after" for e in graph.list_links(db, 2))
    assert db.get(models.Capsule, cap.id).life_event_id == root.id


def test_legacy_graph_without_scenarios_gets_default_goal_and_expected_returns(db):
    node(db)
    cash = account(db)
    config(db)
    data = export_client(db, db.get(models.Client, 1))["data"]
    next(row for row in data["accounts"] if row["id"] == cash.id)["expected_return"] = 3.5
    for key in ("life_scenarios", "life_scenario_account_returns"):
        data.pop(key)
    import_client(db, db.get(models.Client, 2), data=data, version=20, manifest=None)
    goal = service.get_goal(db, 2)
    assert (goal.name, goal.annual_return, goal.inflation, goal.horizon_years) == ("基本シナリオ", 5, 2, 30)
    assert [row["annual_return"] for row in service.account_returns(db, goal)] == [3.5]


@pytest.mark.parametrize("defect", ["scenario_id", "lineage", "duplicate_lineage", "cross_link", "capsule", "alternative"])
def test_v22_invalid_ownership_rejected_before_replace(db, defect):
    original, root, _, _ = story(db)
    cap = earmark(db, root)
    draft = service.duplicate(db, 1, original.id, "別案")
    data = export_client(db, db.get(models.Client, 1))["data"]
    if defect == "scenario_id":
        data["life_events"][0]["scenario_id"] = 99999
    elif defect == "lineage":
        data["life_events"][0]["lineage"] = "bad"
    elif defect == "duplicate_lineage":
        data["life_events"][1]["lineage"] = data["life_events"][0]["lineage"]
    elif defect == "cross_link":
        data["life_event_links"][0]["to_event_id"] = next(e["id"] for e in data["life_events"] if e["scenario_id"] == draft.id)
    elif defect == "capsule":
        data["capsules"][0]["life_event_id"] = next(e["id"] for e in data["life_events"] if e["scenario_id"] == draft.id)
    else:
        data["life_event_links"][0]["kind"] = "alternative"
    assert validate_import_payload(data, 22)["error_count"] > 0
    with pytest.raises(Invalid):
        import_client(db, db.get(models.Client, 1), data=data, version=22, manifest=None)
    assert service.get_goal(db, 1).id == original.id
    assert db.get(models.Capsule, cap.id).life_event_id == root.id


def test_cross_scenario_links_and_alternative_are_refused_in_service_and_http(db, api):
    original, root, children, _ = story(db)
    clone = service.duplicate(db, 1, original.id, "別案")
    target = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=children[0].lineage).one()
    for kind, target_id, message in [("after", target.id, "同じシナリオ"),
                                     ("alternative", children[0].id, "接続は「必ず続く」のみです。")]:
        payload = {"from_event_id": root.id, "to_event_id": target_id, "kind": kind}
        with pytest.raises(Refused, match=message):
            graph.create_link(db, 1, **payload)
        response = request(api, "POST", "/life-events/links", json=payload)
        assert response.status_code == 422 and message in response.text
    assert len(graph.list_links(db, 1)) == 2
    response = request(api, "GET", f"/life-events/links?scenario_id={clone.id}")
    assert response.status_code == 200 and len(response.json()) == 2
    assert {e["from_event_id"] for e in response.json()} == {db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=root.lineage).one().id}


def test_empty_client_gets_empty_event_lists_and_story_comparison(db, api):
    assert request(api, "GET", "/life-events/").json() == []
    assert request(api, "GET", "/life-events/with-progress").json() == []
    first = request(api, "POST", "/life-scenarios", json={"name": "保存"}).json()
    assert first["events"] == [] and not first["is_goal"]
    assert request(api, "POST", f'/life-scenarios/{first["id"]}/goal').status_code == 200
    assert request(api, "POST", "/life-scenarios", json={"name": "保存"}).status_code == 409
    assert request(api, "PUT", f'/life-scenarios/{first["id"]}', json={"name": "改名"}).json()["name"] == "改名"
    foreign = service.create(db, 2, "外部")
    for method, suffix, payload in [("PUT", "", {}), ("PUT", "/account-returns", {"returns": []}),
                                    ("POST", "/goal", {}), ("POST", "/duplicate", {"name": "複製"}), ("DELETE", "", None)]:
        assert request(api, method, f"/life-scenarios/{foreign.id}{suffix}", **({"json": payload} if payload is not None else {})).status_code == 404
    assert request(api, "GET", f'/life-scenarios/compare?ids={first["id"]},{foreign.id}').status_code == 404
    assert request(api, "GET", "/life-scenarios/compare?ids=bad").status_code == 422


def test_duplicate_preserves_archived_facts_and_returns_independent_json(db):
    original, _, children, _ = story(db)
    children[0].archived_at = datetime(2026, 1, 1)
    db.commit()
    clone = service.duplicate(db, 1, original.id, "複製")
    copied = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=children[0].lineage).one()
    assert copied.archived_at == children[0].archived_at
    assert copied.id not in {e.id for e in service.resolve(db, 1, clone).events}
    first = db.query(models.Milestone).filter_by(life_event_id=children[0].id).one()
    second = db.query(models.Milestone).filter_by(life_event_id=copied.id).one()
    second.source_snapshot["nested"].append({"extra": True})
    assert first.source_snapshot["nested"] != second.source_snapshot["nested"]


def test_duplicate_rolls_back_partial_graph_on_failure(db, monkeypatch):
    original, _, _, _ = story(db)
    counts = [db.query(model).count() for model in (models.LifeScenario, models.LifeEvent, models.LifeEventLink, models.Milestone)]
    def fail(*args):
        raise RuntimeError("copy failed")
    monkeypatch.setattr(service, "copy_conditions", fail)
    with pytest.raises(RuntimeError, match="copy failed"):
        service.duplicate(db, 1, original.id, "失敗")
    assert [db.query(model).count() for model in (models.LifeScenario, models.LifeEvent, models.LifeEventLink, models.Milestone)] == counts


def test_database_cascade_deletes_draft_story_without_touching_real_money(db):
    original, root, _, _ = story(db)
    cap = earmark(db, root, claim=500)
    clone = service.duplicate(db, 1, original.id, "複製")
    ids = [e.id for e in db.query(models.LifeEvent).filter_by(scenario_id=clone.id)]
    before = journal_snapshot(db)
    claim = capsule_service.claimed_minor(db, 1, cap.id)
    db.execute(delete(models.LifeScenario).where(models.LifeScenario.id == clone.id))
    db.commit()
    assert not db.query(models.LifeEvent).filter(models.LifeEvent.id.in_(ids)).count()
    assert not db.query(models.LifeEventCondition).filter(models.LifeEventCondition.life_event_id.in_(ids)).count()
    assert not db.query(models.Milestone).filter(models.Milestone.life_event_id.in_(ids)).count()
    assert cap.life_event_id == root.id and capsule_service.claimed_minor(db, 1, cap.id) == claim
    assert journal_snapshot(db) == before


def test_a_story_resolves_more_than_64_events_without_a_branch_cap(db):
    scenario_id = goal_scenario_id(db, 1)
    db.add_all(models.LifeEvent(client_id=1, scenario_id=scenario_id, name=str(index),
                               target_date=date(2030, 1, 1), target_amount_minor=1) for index in range(80))
    db.commit()
    draft = service.create(db, 1, "空")
    assert len(service.resolve(db, 1, service.get_goal(db, 1)).events) == 80
    assert service.resolve(db, 1, draft).events == []


def test_goal_preview_lists_moves_detachments_and_missing_capsules_without_writing(db):
    original, root, children, _ = story(db)
    moved = earmark(db, root, "移る")
    lost = earmark(db, children[0], "外れる")
    clone = service.duplicate(db, 1, original.id, "複製")
    # The clone drops the event that carried "外れる", so its lineage has no target.
    dropped = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=children[0].lineage).one()
    db.delete(dropped)
    db.commit()
    before = journal_snapshot(db)
    preview = service.goal_preview(db, 1, clone.id)
    assert preview["already_goal"] is False
    assert [(row["capsule_name"], row["to_event_name"]) for row in preview["moves"]] == [("移る", root.name)]
    assert [row["capsule_name"] for row in preview["detach"]] == ["外れる"]
    # children[1] has no capsule anywhere, so it would start the goal without one.
    assert [row["event_name"] for row in preview["missing"]] == [children[1].name]
    assert journal_snapshot(db) == before
    assert original.is_goal and not clone.is_goal
    assert db.get(models.Capsule, moved.id).life_event_id == root.id
    assert db.get(models.Capsule, lost.id).life_event_id == children[0].id


def test_goal_preview_for_the_current_goal_reports_only_events_without_capsules(db):
    original, root, children, _ = story(db)
    earmark(db, root, "あり")
    preview = service.goal_preview(db, 1, original.id)
    assert preview["already_goal"] is True and preview["moves"] == [] and preview["detach"] == []
    assert {row["event_id"] for row in preview["missing"]} == {child.id for child in children}


def test_goal_preview_skips_income_and_archived_events(db):
    original, root, children, _ = story(db)
    children[0].direction = "income"
    children[1].archived_at = datetime.utcnow()
    db.commit()
    preview = service.goal_preview(db, 1, original.id)
    assert [row["event_id"] for row in preview["missing"]] == [root.id]


def test_monthly_savings_defaults_to_config_then_belongs_to_the_scenario(db, api):
    config(db, monthly_savings_minor=40000)
    goal = service.get(db, 1, goal_scenario_id(db, 1))
    described = service.describe(db, 1, goal)
    assert (described["monthly_savings"], described["monthly_savings_is_default"]) == (40000, True)
    response = request(api, "PUT", f"/life-scenarios/{goal.id}", json={"monthly_savings": 65000})
    assert response.status_code == 200
    assert (response.json()["monthly_savings"], response.json()["monthly_savings_is_default"]) == (65000, False)
    # A new story starts from the goal's assumptions, savings included; the copy is independent.
    draft = service.create(db, 1, "別案")
    assert service.describe(db, 1, draft)["monthly_savings"] == 65000
    service.update(db, 1, draft.id, {"monthly_savings": 10000})
    assert service.describe(db, 1, goal)["monthly_savings"] == 65000
    # null hands the scenario back to the client-wide setting.
    response = request(api, "PUT", f"/life-scenarios/{goal.id}", json={"monthly_savings": None})
    assert (response.json()["monthly_savings"], response.json()["monthly_savings_is_default"]) == (40000, True)
    assert request(api, "PUT", f"/life-scenarios/{goal.id}", json={"monthly_savings": -1}).status_code == 422


def test_projection_and_event_context_use_the_scenario_savings(db):
    from app.services.strategy_service import get_goal_simulation_context
    config(db, monthly_savings_minor=0, volatility=0)
    goal = service.get(db, 1, goal_scenario_id(db, 1))
    event = node(db, "家", amount=1_000_000, scenario_id=goal.id)
    before = service.project(db, 1, goal)["projection"][-1]["p50"]
    service.update(db, 1, goal.id, {"monthly_savings": 30000})
    after = service.project(db, 1, goal)["projection"][-1]["p50"]
    assert after > before
    assert get_goal_simulation_context(db, 1, event)["monthly_savings"] == 30000


def test_budget_reflection_follows_preconditions_until_chosen(db, api):
    _, root, children, _ = story(db)
    assert root.budget_reflection_effective == "firm"
    # children[0] carries a precondition from story().
    assert children[0].budget_reflection_effective == "conditional"
    response = request(api, "PUT", f"/life-events/{children[0].id}", json={"budget_reflection": "simulation_only"})
    assert response.status_code == 200
    assert response.json()["budget_reflection_effective"] == "simulation_only"
    assert request(api, "PUT", f"/life-events/{root.id}", json={"budget_reflection": "maybe"}).status_code == 422
    # Duplicating a story keeps each event's choice.
    clone = service.duplicate(db, 1, service.get_goal(db, 1).id, "複製")
    copied = db.query(models.LifeEvent).filter_by(scenario_id=clone.id, lineage=children[0].lineage).one()
    assert copied.budget_reflection == "simulation_only"
