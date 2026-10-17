"""Saved scenarios keep branch decisions and financial assumptions together."""
import asyncio
import importlib.util
from datetime import date
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, Invalid, NotFound, Refused, detail_for, status_for
from app.domain.transfer import EXPORT_VERSION, validate_import_payload
from app.routers.life_scenarios import router
from app.routers.life_events import router as legacy_router
from app.services import life_scenario_service as service, life_event_graph as graph
from app.services.data_transfer_service import export_client, import_client
from app.services.institution_service import blended_after_tax_return
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


def node(db, name="予定", client_id=1, **kwargs):
    row = models.LifeEvent(client_id=client_id, name=name, target_date=date(date.today().year + 1, 1, 31),
                           target_amount_minor=kwargs.pop("amount", 0), **kwargs)
    db.add(row)
    db.commit()
    return row


def fork(db, name="進路", source=None, client_id=1):
    source = source or node(db, name, client_id=client_id)
    children = [node(db, name + suffix, client_id=client_id) for suffix in ("甲", "乙")]
    edges = [graph.create_link(db, client_id, from_event_id=source.id, to_event_id=child.id,
                               kind="alternative", offset_months=1) for child in children]
    return source, children, edges


def account(db, name="口座", client_id=1, kind="asset", rate=None, balance=0, institution="none"):
    row = create_account(db, client_id, {"name": name, "account_type": kind, "expected_return": rate, "institution": institution})
    if balance:
        income = create_account(db, client_id, {"name": "給与", "account_type": "income"})
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


def test_resolve_uses_selected_branch_and_later_fork_defaults_without_persisting(db):
    root, children, edges = fork(db)
    scenario = service.create(db, 1, "進学")
    service.replace_choices(db, 1, scenario.id, [edges[1].id])
    resolved = service.resolve(db, 1, scenario)
    assert resolved.missing_forks == []
    assert [event.id for event in resolved.events] == [root.id, children[1].id]
    assert resolved.events[-1].resolved_date.month == 2
    later, later_children, later_edges = fork(db, "住居")
    resolved = service.resolve(db, 1, scenario)
    assert resolved.missing_forks == [later.id]
    assert {event.id for event in resolved.events} == {root.id, children[1].id, later.id, later_children[0].id}
    assert resolved.chosen_link_ids == [edges[1].id, later_edges[0].id]
    assert service.choice_ids(db, scenario) == [edges[1].id]


def test_resolve_does_not_enumerate_or_stop_at_legacy_cap(db):
    edges = [fork(db, str(index))[2] for index in range(8)]
    scenario = service.create(db, 1, "すべて乙")
    service.replace_choices(db, 1, scenario.id, [pair[1].id for pair in edges])
    service.make_goal(db, 1, scenario.id)
    resolved = service.resolve(db, 1, scenario)
    assert resolved.chosen_link_ids == [pair[1].id for pair in edges]
    assert len(resolved.events) == 16 and resolved.missing_forks == []
    enumerated = graph.enumerate_scenarios(db, 1)
    assert enumerated.truncated
    adoption = graph.adopted_scenario(db, 1, enumerated)
    assert adoption.exact and adoption.scenario.chosen_link_ids == resolved.chosen_link_ids


@pytest.mark.parametrize("removal", ["service", "sql", "event"])
def test_deleted_choice_cascades_and_reports_missing_fork(db, removal):
    root, children, edges = fork(db)
    scenario = service.create(db, 1, "保存")
    service.replace_choices(db, 1, scenario.id, [edges[1].id])
    if removal == "service":
        graph.delete_link(db, 1, edges[1].id)
    elif removal == "sql":
        db.execute(delete(models.LifeEventLink).where(models.LifeEventLink.id == edges[1].id))
        db.commit()
    else:
        db.execute(delete(models.LifeEvent).where(models.LifeEvent.id == children[1].id))
        db.commit()
    assert service.choice_ids(db, scenario) == []
    assert service.resolve(db, 1, scenario).missing_forks == [root.id]
    assert db.query(models.LifeScenarioChoice).count() == 0


@pytest.mark.parametrize("invalid", ["after", "same_fork", "foreign", "missing"])
def test_choice_validation_leaves_previous_choices_intact(db, invalid):
    root, children, edges = fork(db)
    scenario = service.create(db, 1, "保存")
    service.replace_choices(db, 1, scenario.id, [edges[1].id])
    if invalid == "after":
        bad = graph.create_link(db, 1, from_event_id=root.id, to_event_id=node(db, "共通").id, kind="after")
        ids = [bad.id]
    elif invalid == "same_fork":
        ids = [edge.id for edge in edges]
    elif invalid == "foreign":
        ids = [fork(db, client_id=2)[2][0].id]
    else:
        ids = [99999]
    with pytest.raises(Refused) as error:
        service.replace_choices(db, 1, scenario.id, ids)
    assert error.value.status_code == 422
    assert service.choice_ids(db, scenario) == [edges[1].id]
    service.replace_choices(db, 1, scenario.id, [])
    assert service.choice_ids(db, scenario) == []


def test_override_expected_and_gross_precedence_including_zero_and_tax(db):
    row = account(db, rate=10, balance=10000)
    assert blended_after_tax_return(db, 1, gross_annual_return=20, tax_rate=25) == 7.5
    assert blended_after_tax_return(db, 1, gross_annual_return=20, tax_rate=25, account_returns={row.id: 4}) == 3
    assert blended_after_tax_return(db, 1, gross_annual_return=20, tax_rate=25, account_returns={row.id: 0}) == 0
    row.expected_return = None
    db.commit()
    assert blended_after_tax_return(db, 1, gross_annual_return=20, tax_rate=25) == 15
    row.institution = "nisa_growth"
    db.commit()
    assert blended_after_tax_return(db, 1, gross_annual_return=20, tax_rate=25, account_returns={row.id: 4}) == 4


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


def test_projections_use_individual_assumptions_and_resolved_cash_flows(db):
    config(db, volatility=0)
    asset = account(db, rate=0, balance=100000)
    root, children, edges = fork(db)
    root.target_amount_minor = 100
    children[1].target_amount_minor = 900
    children[1].direction = "income"
    db.commit()
    lower = service.create(db, 1, "低め")
    service.update(db, 1, lower.id, {"annual_return": 1, "inflation": 0, "horizon_years": 3})
    service.replace_choices(db, 1, lower.id, [edges[1].id])
    higher = service.duplicate(db, 1, lower.id, "高め")
    assert service.project(db, 1, lower)["projection"] == service.project(db, 1, higher)["projection"]
    service.update(db, 1, higher.id, {"annual_return": 9})
    low, high = [service.project(db, 1, item)["projection"] for item in (lower, higher)]
    assert high[-1]["p50"] > low[-1]["p50"]
    assert low[-1]["cumulative_target"] == 100 and low[-1]["cumulative_income"] == 900
    service.replace_account_returns(db, 1, lower.id, [{"account_id": asset.id, "annual_return": 10}])
    assert service.project(db, 1, lower)["projection"][-1]["p50"] > low[-1]["p50"]
    assert asset.expected_return == 0


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


def test_duplicate_and_create_copy_correct_parts_and_delete_cascades(db):
    edges = fork(db)[2]
    asset = account(db)
    goal = service.create(db, 1, "保存")
    service.update(db, 1, goal.id, {"annual_return": 8, "inflation": 1, "horizon_years": 11})
    service.replace_choices(db, 1, goal.id, [edges[1].id])
    service.replace_account_returns(db, 1, goal.id, [{"account_id": asset.id, "annual_return": 4}])
    service.make_goal(db, 1, goal.id)
    new = service.create(db, 1, "新規")
    clone = service.duplicate(db, 1, goal.id, "複製")
    for item in (new, clone):
        assert (item.annual_return, item.inflation, item.horizon_years, item.is_goal) == (8, 1, 11, False)
        assert service.account_returns(db, item) == service.account_returns(db, goal)
    assert service.choice_ids(db, new) == []
    assert service.choice_ids(db, clone) == [edges[1].id]
    service.delete(db, 1, clone.id)
    assert not db.query(models.LifeScenarioChoice).filter_by(scenario_id=clone.id).count()
    assert not db.query(models.LifeScenarioAccountReturn).filter_by(scenario_id=clone.id).count()
    db.execute(delete(models.Account).where(models.Account.id == asset.id))
    db.commit()
    assert service.account_returns(db, goal) == []


def test_defaults_do_not_use_config_or_account_rates_for_new_scenarios_without_goal(db):
    config(db)
    account(db, rate=9)
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


def test_v21_roundtrip_remaps_all_refs_and_replaces_old_goal(db):
    root, _, edges = fork(db)
    asset = account(db, rate=3)
    scenario = service.create(db, 1, "保存")
    service.replace_choices(db, 1, scenario.id, [edges[1].id])
    service.replace_account_returns(db, 1, scenario.id, [{"account_id": asset.id, "annual_return": 7}])
    service.make_goal(db, 1, scenario.id)
    service.duplicate(db, 1, scenario.id, "別案")
    target_goal = service.create(db, 2, "既存")
    service.make_goal(db, 2, target_goal.id)
    document = export_client(db, db.get(models.Client, 1))
    assert EXPORT_VERSION == document["version"] == 21
    assert all("adopted" not in link for link in document["data"]["life_event_links"])
    source_projection = service.project(db, 1, scenario)["projection"]
    for _ in range(2):
        import_client(db, db.get(models.Client, 2), data=document["data"], version=21, manifest=document["manifest"])
        restored = service.get_goal(db, 2)
        assert restored.id != scenario.id
        assert restored.name == scenario.name
        assert service.project(db, 2, restored)["projection"] == source_projection
        assert set(service.choice_ids(db, restored)).isdisjoint(service.choice_ids(db, scenario))
        rates = service.account_returns(db, restored)
        assert rates[0]["account_id"] != asset.id and rates[0]["annual_return"] == 7
    assert len(service.list_scenarios(db, 2)) == 2
    assert service.get_goal(db, 1).id == scenario.id


def test_v20_import_creates_goal_using_config_and_legacy_asset_returns(db):
    edges = fork(db)[2]
    asset = account(db, rate=3.5, balance=10000)
    account(db, name="未設定", rate=None)
    account(db, name="収入", kind="income", rate=99)
    config(db)
    before = graph.project_scenario(db, 1, graph.enumerate_scenarios(db, 1)[1], years=8, annual_return=7.5, inflation=1.5)
    document = export_client(db, db.get(models.Client, 1))
    data = document["data"]
    for key in ("life_scenarios", "life_scenario_choices", "life_scenario_account_returns"):
        del data[key]
    for link in data["life_event_links"]:
        link["adopted"] = link["id"] == edges[1].id
    import_client(db, db.get(models.Client, 2), data=data, version=20, manifest=None)
    scenario = service.get_goal(db, 2)
    assert scenario.name == "進路乙"
    assert (scenario.annual_return, scenario.inflation, scenario.horizon_years) == (7.5, 1.5, 8)
    assert len(service.choice_ids(db, scenario)) == 1
    assert [row["annual_return"] for row in service.account_returns(db, scenario)] == [3.5]
    assert service.project(db, 2, scenario)["projection"] == before


def test_seed_legacy_goal_defaults_and_no_events(db):
    assert service.seed_legacy_goal(db, 1, []) is None
    node(db)
    scenario = service.seed_legacy_goal(db, 1, [])
    db.commit()
    assert (scenario.name, scenario.is_goal, scenario.annual_return, scenario.inflation, scenario.horizon_years) == ("基本シナリオ", True, 5, 2, 30)


def test_migration_both_directions_preserve_branch_assumptions_and_projection(db):
    root, _, edges = fork(db)
    second_edges = fork(db, "住居")[2]
    asset = account(db, rate=3.5, balance=10000)
    account(db, name="未設定", rate=None)
    account(db, name="費用", kind="expense", rate=99)
    config(db)
    node(db, "既定", client_id=2)
    chosen = graph.enumerate_scenarios(db, 1)[-1]
    before = graph.project_scenario(db, 1, chosen, years=8, annual_return=7.5, inflation=1.5)
    db.commit()
    spec = importlib.util.spec_from_file_location("ls1_migration", Path(__file__).parents[1] / "alembic/versions/20261017_0067_life_scenarios.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = db.get_bind()
    with engine.begin() as connection:
        for table in (models.LifeScenarioAccountReturn.__table__, models.LifeScenarioChoice.__table__, models.LifeScenario.__table__):
            table.drop(connection)
        connection.execute(text("ALTER TABLE life_event_links ADD COLUMN adopted BOOLEAN NOT NULL DEFAULT false"))
        for link_id in chosen.chosen_link_ids:
            connection.execute(text("UPDATE life_event_links SET adopted = true WHERE id = :id"), {"id": link_id})
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    db.expire_all()
    scenario = service.get_goal(db, 1)
    assert scenario.name == chosen.label
    assert service.choice_ids(db, scenario) == chosen.chosen_link_ids
    assert (scenario.annual_return, scenario.inflation, scenario.horizon_years) == (7.5, 1.5, 8)
    assert service.account_returns(db, scenario) == [{"account_id": asset.id, "annual_return": 3.5}]
    assert service.project(db, 1, scenario)["projection"] == before
    assert service.get_goal(db, 2).name == "基本シナリオ"
    assert service.get_goal(db, 3) is None
    assert "adopted" not in {col["name"] for col in inspect(engine).get_columns("life_event_links")}
    # Downgrade must restore the current goal, including a switch made after upgrade.
    replacement = service.duplicate(db, 1, scenario.id, "変更後")
    service.replace_choices(db, 1, replacement.id, [edges[0].id, second_edges[1].id])
    service.make_goal(db, 1, replacement.id)
    db.commit()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        marked = connection.execute(text("SELECT id FROM life_event_links WHERE adopted ORDER BY id")).scalars().all()
        assert marked == [edges[0].id, second_edges[1].id]
        assert not {"life_scenarios", "life_scenario_choices", "life_scenario_account_returns"} & set(inspect(connection).get_table_names())
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    db.expire_all()
    assert service.choice_ids(db, service.get_goal(db, 1)) == marked


@pytest.mark.parametrize("collection, field", [("life_scenario_choices", "scenario_id"), ("life_scenario_choices", "link_id"),
    ("life_scenario_account_returns", "scenario_id"), ("life_scenario_account_returns", "account_id")])
def test_backup_validates_new_references_before_replace(db, collection, field):
    edges = fork(db)[2]
    asset = account(db)
    scenario = service.create(db, 1, "保存")
    service.replace_choices(db, 1, scenario.id, [edges[1].id])
    service.replace_account_returns(db, 1, scenario.id, [{"account_id": asset.id, "annual_return": 3}])
    data = export_client(db, db.get(models.Client, 1))["data"]
    data[collection][0][field] = 99999
    validation = validate_import_payload(data, 21)
    assert any(row["code"] == "missing_reference" and row.get("field") == field for row in validation["issues"])
    with pytest.raises(Invalid):
        import_client(db, db.get(models.Client, 1), data=data, version=21, manifest=None)
    assert service.get(db, 1, scenario.id).name == "保存"


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(router)
    app.include_router(legacy_router)
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


def test_http_crud_compare_and_legacy_fallback_with_goal_assumptions(db, api):
    edges = fork(db)[2]
    asset = account(db, rate=3)
    config(db)
    create = request(api, "POST", "/life-scenarios", json={"name": "  新規  "})
    assert create.status_code == 200
    scenario_id = create.json()["id"]
    base = f"/life-scenarios/{scenario_id}"
    assert request(api, "PUT", base, json={"annual_return": 9, "inflation": 0, "horizon_years": 2}).status_code == 200
    assert request(api, "PUT", base + "/choices", json={"link_ids": [edges[1].id]}).json()["choices"] == [edges[1].id]
    assert request(api, "PUT", base + "/account-returns", json={"returns": [{"account_id": asset.id, "annual_return": 10}]}).status_code == 200
    assert request(api, "POST", base + "/goal").json()["is_goal"] is True
    assert request(api, "DELETE", base).status_code == 422
    clone = request(api, "POST", base + "/duplicate", json={"name": "複製"}).json()
    assert not clone["is_goal"] and clone["choices"] == [edges[1].id]
    assert request(api, "PUT", f'/life-scenarios/{clone["id"]}', json={"annual_return": 0}).status_code == 200
    compare = request(api, "GET", f'/life-scenarios/compare?ids={scenario_id},{clone["id"]}')
    assert compare.status_code == 200
    assert [row["annual_return"] for row in compare.json()["scenarios"]] == [9, 0]
    assert compare.json()["scenarios"][0]["projection"] != compare.json()["scenarios"][1]["projection"]
    legacy = request(api, "GET", "/life-events/scenarios").json()
    assert legacy["parameters"] == {"years": 2, "annual_return": 9, "inflation": 0}
    assert legacy["adopted"] == {"scenario_id": str(edges[1].id), "exact": True}
    assert legacy["scenarios"][1]["projection"] == compare.json()["scenarios"][0]["projection"]
    assert request(api, "GET", "/life-events/scenarios?annual_return=0").json()["parameters"]["annual_return"] == 0
    assert request(api, "POST", "/life-events/scenarios/adopt", json={"scenario_id": str(edges[0].id)}).json()["exact"]
    assert service.choice_ids(db, service.get_goal(db, 1)) == [edges[0].id]
    assert request(api, "GET", "/life-scenarios").json()[0]["name"] == "新規"
    assert request(api, "POST", f'/life-scenarios/{clone["id"]}/goal').status_code == 200
    assert request(api, "DELETE", base).status_code == 200


@pytest.mark.parametrize("patch", [{"name": " "}, {"annual_return": "nan"}, {"annual_return": None},
    {"inflation": "Infinity"}, {"horizon_years": 0}, {"horizon_years": 61}, {"horizon_years": 1.5}, {"horizon_years": None}])
def test_http_rejects_invalid_assumptions_in_japanese(db, api, patch):
    scenario = service.create(db, 1, "保存")
    response = request(api, "PUT", f"/life-scenarios/{scenario.id}", json=patch)
    assert response.status_code == 422
    assert any("指定してください" in row["msg"] or "入力してください" in row["msg"] for row in response.json()["detail"])


def test_http_names_and_client_isolation(db, api):
    scenario = service.create(db, 1, "保存")
    other = service.create(db, 1, "別案")
    foreign = service.create(db, 2, "外部")
    assert request(api, "POST", "/life-scenarios", json={"name": "保存"}).status_code == 409
    assert request(api, "POST", "/life-scenarios", json={"name": " "}).status_code == 422
    assert request(api, "POST", f"/life-scenarios/{scenario.id}/duplicate", json={"name": "別案"}).status_code == 409
    assert request(api, "PUT", f"/life-scenarios/{scenario.id}", json={"name": "別案"}).status_code == 409
    for method, suffix, payload in [("PUT", "", {}), ("PUT", "/choices", {"link_ids": []}),
        ("PUT", "/account-returns", {"returns": []}), ("POST", "/goal", None), ("POST", "/duplicate", {"name": "複製"}), ("DELETE", "", None)]:
        assert request(api, method, f"/life-scenarios/{foreign.id}{suffix}", **({"json": payload} if payload is not None else {})).status_code == 404
    assert request(api, "GET", f"/life-scenarios/compare?ids={scenario.id},{foreign.id}").status_code == 404
    assert request(api, "GET", "/life-scenarios/compare?ids=bad").status_code == 422


def test_legacy_adopt_can_create_first_goal_after_an_existing_default_named_scenario(db, api):
    edges = fork(db)[2]
    service.create(db, 1, "基本シナリオ")
    config(db)
    response = request(api, "POST", "/life-events/scenarios/adopt", json={"scenario_id": str(edges[1].id)})
    assert response.status_code == 200
    assert service.get_goal(db, 1).annual_return == 7.5


@pytest.mark.parametrize("defect", ["name", "duplicate_name", "goals", "horizon", "rate", "missing_rate", "same_fork", "after", "non_asset", "duplicate_account"])
def test_backup_rejects_invalid_scenario_semantics_before_replace(db, defect):
    root, _, edges = fork(db)
    asset = account(db)
    scenario = service.create(db, 1, "保存")
    service.replace_choices(db, 1, scenario.id, [edges[1].id])
    service.replace_account_returns(db, 1, scenario.id, [{"account_id": asset.id, "annual_return": 3}])
    service.make_goal(db, 1, scenario.id)
    data = export_client(db, db.get(models.Client, 1))["data"]
    if defect == "name":
        data["life_scenarios"][0]["name"] = " "
    elif defect in {"duplicate_name", "goals"}:
        data["life_scenarios"].append({**data["life_scenarios"][0], "id": 900,
            "name": "保存" if defect == "duplicate_name" else "追加", "is_goal": defect == "goals"})
    elif defect == "horizon":
        data["life_scenarios"][0]["horizon_years"] = 61
    elif defect == "rate":
        data["life_scenarios"][0]["inflation"] = float("inf")
    elif defect == "missing_rate":
        del data["life_scenario_account_returns"][0]["annual_return"]
    elif defect == "same_fork":
        data["life_scenario_choices"].append({"id": 900, "scenario_id": scenario.id, "link_id": edges[0].id})
    elif defect == "after":
        data["life_event_links"][1]["kind"] = "after"
    elif defect == "non_asset":
        data["accounts"][0]["account_type"] = "income"
    else:
        data["life_scenario_account_returns"].append({**data["life_scenario_account_returns"][0], "id": 900})
    assert validate_import_payload(data, 21)["error_count"] > 0
    with pytest.raises(Invalid):
        import_client(db, db.get(models.Client, 1), data=data, version=21, manifest=None)
    assert service.get_goal(db, 1).id == scenario.id


def test_unreached_forks_do_not_require_choices(db):
    root, children, edges = fork(db)
    nested, _, _ = fork(db, "未選択の先", source=children[1])
    scenario = service.create(db, 1, "甲")
    service.replace_choices(db, 1, scenario.id, [edges[0].id])
    resolved = service.resolve(db, 1, scenario)
    assert resolved.missing_forks == []
    assert nested.id not in {event.id for event in resolved.events}
