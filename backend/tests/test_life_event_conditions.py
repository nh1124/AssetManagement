"""Assumptions are observations, including unknown references, never plan actions."""
import asyncio
from datetime import date

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scenario_fixtures import goal_scenario_id

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, Invalid, NotFound, detail_for, status_for
from app.domain.transfer import EXPORT_VERSION
from app.services import life_event_conditions as conditions
from app.services import household_service
from app.services.analysis_service import calculate_logical_balance
from app.services.reporting_service import get_balance_sheet
from app.services.capsule_service import claimed_minor
from app.services.data_transfer_service import export_client, import_client
from app.services.goal_service import delete_goal
from app.services.ledger_service import create_transaction
from app.services import life_scenario_service as saved
from app.services.strategy_service import get_life_events_with_progress


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add_all([models.Client(id=1, name="本人", general_settings={"currency": "JPY"}),
                         models.Client(id=2, name="別人", general_settings={"currency": "JPY"})])
        session.commit()
        yield session
    engine.dispose()


def goal(db, name="進学", client_id=1, mode="all"):
    row = models.LifeEvent(scenario_id=goal_scenario_id(db, client_id), client_id=client_id, name=name, target_date=date.today().replace(year=date.today().year + 2), target_amount_minor=1000, condition_mode=mode)
    db.add(row)
    db.commit()
    return row


def add(db, owner, metric, reference_id=None, comparator="gte", **threshold):
    if not threshold:
        threshold = {"threshold_date": date.today()} if metric == "date_reached" else {"threshold_number": 18} if metric in {"member_age", "goal_progress"} else {"threshold_minor": 100}
    return conditions.create_condition(db, owner.client_id, owner.id, schemas.LifeEventConditionCreate(metric=metric, comparator=comparator, reference_id=reference_id, **threshold))


def finances(db, currency="JPY", minor=500):
    cash = models.Account(client_id=1, name="cash", account_type="asset")
    income = models.Account(client_id=1, name="給与", account_type="income")
    capsule = models.Capsule(client_id=1, name="学費", target_amount_minor=1000)
    db.add_all([cash, income, capsule])
    db.commit()
    tx = create_transaction(db, client_id=1, date=date.today(), amount_minor=minor, currency=currency, description="積立", from_account_id=income.id, to_account_id=cash.id)
    leg = db.query(models.JournalEntry).filter_by(transaction_id=tx.id, account_id=cash.id).one()
    leg.capsule_id = capsule.id
    db.commit()
    return cash, capsule


def result(db, owner, as_of=None):
    return conditions.evaluate(db, owner.client_id, owner.id, as_of=as_of)["conditions"][0]


@pytest.mark.parametrize("metric", ["net_worth", "free_cash", "account_balance", "capsule_claim", "goal_progress", "member_age", "date_reached"])
def test_each_metric_reads_its_existing_figure(db, metric):
    owner = goal(db)
    cash, capsule = finances(db)
    capsule.life_event_id = owner.id
    member = household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="子", birth_date=date(2010, 10, 15)))
    db.commit()
    references = {"account_balance": cash.id, "capsule_claim": capsule.id, "goal_progress": owner.id, "member_age": member.id}
    add(db, owner, metric, references.get(metric))
    actual = result(db, owner, date(2028, 10, 15))["actual"]
    expected = {
        "net_worth": get_balance_sheet(db, client_id=1)["net_worth"],
        "free_cash": calculate_logical_balance(db, 1), "account_balance": 500,
        "capsule_claim": claimed_minor(db, 1, capsule.id)["JPY"],
        "goal_progress": get_life_events_with_progress(db, 1)[0]["progress_percentage"],
        "member_age": 18, "date_reached": date(2028, 10, 15),
    }
    assert actual == expected[metric]
    assert result(db, owner)["reference_name"] == ({"account_balance": cash.name, "capsule_claim": capsule.name, "goal_progress": owner.name, "member_age": member.name}.get(metric))


@pytest.mark.parametrize("mode, values, expected", [
    ("all", [True, True], True), ("all", [True, False], False),
    ("any", [True, False], True), ("any", [False, False], False),
    ("all", [True, None], None), ("all", [False, None], False),
    ("any", [True, None], True), ("any", [False, None], None),
    ("any", [None, None], None), ("all", [None, None], None),
])
def test_combination_preserves_unknown_unless_a_sibling_decides(db, mode, values, expected):
    owner = goal(db, mode=mode)
    cash, _ = finances(db)
    for value in values:
        row = add(db, owner, "account_balance", cash.id, threshold_minor=100 if value else 1000)
        if value is None:
            row.reference_id = 99999
    db.commit()
    assert conditions.evaluate(db, 1, owner.id)["satisfied"] is expected


@pytest.mark.parametrize("mode", ["all", "any"])
def test_no_conditions_is_no_assumptions(db, mode):
    owner = goal(db, mode=mode)
    assert conditions.evaluate(db, 1, owner.id) == {"mode": mode, "satisfied": None, "conditions": []}


@pytest.mark.parametrize("metric", ["account_balance", "capsule_claim", "member_age", "goal_progress"])
def test_missing_or_other_client_reference_is_unknown(db, metric):
    owner = goal(db)
    row = models.LifeEventCondition(client_id=1, life_event_id=owner.id, metric=metric, comparator="gte", threshold_minor=1 if metric in conditions.MONEY_METRICS else None, threshold_number=1 if metric not in conditions.MONEY_METRICS else None, reference_id=99999)
    db.add(row)
    db.commit()
    assert result(db, owner)["satisfied"] is None
    assert result(db, owner)["reason"]
    if metric == "goal_progress":
        row.reference_id = goal(db, client_id=2).id
        db.commit()
        assert result(db, owner)["actual"] is None


@pytest.mark.parametrize("metric", ["capsule_claim", "account_balance", "net_worth", "free_cash", "goal_progress"])
def test_foreign_money_is_unknown_instead_of_converted_or_discarded(db, metric):
    owner = goal(db)
    cash, capsule = finances(db, currency="USD")
    capsule.life_event_id = owner.id
    db.add(models.ExchangeRate(client_id=1, base_currency="USD", quote_currency="JPY", rate=150, as_of_date=date.today()))
    db.commit()
    add(db, owner, metric, {"account_balance": cash.id, "capsule_claim": capsule.id, "goal_progress": owner.id}.get(metric))
    evaluated = result(db, owner)
    assert evaluated["actual"] is None and evaluated["satisfied"] is None
    assert "通貨" in evaluated["reason"]


@pytest.mark.parametrize("as_of, age", [(date(2028, 10, 14), 17), (date(2028, 10, 15), 18), (date(2028, 10, 16), 18)])
def test_age_counts_whole_years_on_birthday(db, as_of, age):
    owner = goal(db)
    member = household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="子", birth_date=date(2010, 10, 15)))
    add(db, owner, "member_age", member.id)
    assert result(db, owner, as_of)["actual"] == age
    assert result(db, owner, as_of)["satisfied"] is (age >= 18)


@pytest.mark.parametrize("as_of, age", [(date(2027, 2, 28), 18), (date(2027, 3, 1), 19), (date(2028, 2, 29), 20)])
def test_leap_day_age_uses_calendar_anniversary(db, as_of, age):
    owner = goal(db)
    member = household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="子", birth_date=date(2008, 2, 29)))
    add(db, owner, "member_age", member.id)
    assert result(db, owner, as_of)["actual"] == age


@pytest.mark.parametrize("comparator, threshold, expected", [("gte", 500, True), ("lte", 499, False), ("eq", 500, True), ("eq", 501, False)])
def test_money_compares_minor_units_in_client_currency(db, comparator, threshold, expected):
    client = db.get(models.Client, 1)
    client.general_settings = {"currency": "USD"}
    db.commit()
    owner = goal(db)
    cash, _ = finances(db, currency="USD", minor=500)
    add(db, owner, "account_balance", cash.id, comparator=comparator, threshold_minor=threshold)
    evaluated = result(db, owner)
    assert evaluated["actual"] == 5 and evaluated["threshold"] == threshold / 100
    assert evaluated["satisfied"] is expected


@pytest.mark.parametrize("delete_via_sql", [True, False])
def test_event_delete_cascades_but_member_delete_leaves_reported_assumption(db, delete_via_sql):
    owner = goal(db)
    member = household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="子", birth_date=date(2010, 1, 1)))
    add(db, owner, "member_age", member.id)
    household_service.delete_member(db, 1, member.id)
    assert result(db, owner)["satisfied"] is None
    if delete_via_sql:
        db.execute(delete(models.LifeEvent).where(models.LifeEvent.id == owner.id))
        db.commit()
    else:
        assert delete_goal(db, 1, owner.id)
    assert db.query(models.LifeEventCondition).count() == 0


def test_bulk_evaluation_is_scoped_and_financial_reader_runs_once(db, monkeypatch):
    owners = [goal(db, str(i)) for i in range(5)]
    goal(db, client_id=2)
    for owner in owners:
        add(db, owner, "net_worth")
    calls = []
    original = conditions.get_balance_sheet
    def read(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(conditions, "get_balance_sheet", read)
    assert set(conditions.evaluate_all(db, 1)) == {owner.id for owner in owners}
    assert len(calls) == 1


def test_evaluation_does_not_flush_pending_changes_or_modify_projection(db):
    owner = goal(db)
    add(db, owner, "date_reached", threshold_date=date(2099, 1, 1))
    scenario = saved.get_goal(db, 1)
    saved.update(db, 1, scenario.id, {"horizon_years": 2, "annual_return": 0, "inflation": 0})
    before = saved.compare(db, 1, str(scenario.id))
    owner.note = "未保存"
    writes = []
    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def observe(_, __, statement, ___, ____, _____):
        if statement.split()[0].upper() in {"UPDATE", "INSERT", "DELETE"}:
            writes.append(statement)
    assert conditions.evaluate(db, 1, owner.id)["satisfied"] is False
    assert conditions.evaluate_all(db, 1)[owner.id]["satisfied"] is False
    assert not writes
    db.rollback()
    assert saved.compare(db, 1, str(scenario.id)) == before


def test_backup_remaps_every_reference_and_preserves_dangling_without_id_collision(db):
    owner = goal(db, mode="any")
    cash, capsule = finances(db)
    member = household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="子", birth_date=date(2010, 1, 1)))
    for metric, ref in [("account_balance", cash.id), ("capsule_claim", capsule.id), ("goal_progress", owner.id), ("member_age", member.id)]:
        add(db, owner, metric, ref)
    missing = add(db, owner, "member_age", member.id)
    missing.reference_id = 99999
    add(db, owner, "date_reached", threshold_date=date(2030, 4, 1))
    db.commit()
    source, target = db.get(models.Client, 1), db.get(models.Client, 2)
    document = export_client(db, source)
    assert document["version"] == EXPORT_VERSION == 25
    for _ in range(2):
        import_client(db, target, data=document["data"], version=17, manifest=document["manifest"])
        restored = db.query(models.LifeEvent).filter_by(client_id=2).one()
        assert restored.condition_mode == "any"
        rows = db.query(models.LifeEventCondition).filter_by(client_id=2).order_by(models.LifeEventCondition.id).all()
        assert len(rows) == 6
        for row in rows[:4]:
            model = conditions.REFERENCE_MODELS[row.metric]
            fact = db.get(model, row.reference_id)
            assert fact.client_id == 2
            assert row.life_event_id == restored.id
        assert rows[4].reference_id is None
        assert rows[5].threshold_date == date(2030, 4, 1)
        assert conditions.evaluate(db, 2, restored.id)["conditions"][4]["satisfied"] is None
    assert db.query(models.LifeEventCondition).filter_by(client_id=1).count() == 6


@pytest.mark.parametrize("defect", ["mode", "metric", "comparator", "threshold", "date"])
def test_invalid_backup_is_rejected_before_replacement(db, defect):
    owner = goal(db)
    add(db, owner, "date_reached")
    document = export_client(db, db.get(models.Client, 1))
    if defect == "mode":
        document["data"]["life_events"][0]["condition_mode"] = "bad"
    else:
        row = document["data"]["life_event_conditions"][0]
        row[{"metric": "metric", "comparator": "comparator", "threshold": "threshold_minor", "date": "threshold_date"}[defect]] = "bad"
    with pytest.raises(Invalid):
        import_client(db, db.get(models.Client, 1), data=document["data"], version=17, manifest=None)
    assert db.query(models.LifeEventCondition).count() == 1


@pytest.mark.parametrize("payload", [
    {"metric": "date_reached", "threshold_minor": 1},
    {"metric": "net_worth", "threshold_minor": 1, "threshold_number": 1},
    {"metric": "member_age", "threshold_number": 18},
    {"metric": "capsule_claim", "threshold_minor": 1.5, "reference_id": 1},
    {"metric": "goal_progress", "threshold_number": float("nan"), "reference_id": 1},
])
def test_schema_refuses_wrong_threshold_shapes(payload):
    with pytest.raises(ValidationError):
        schemas.LifeEventConditionCreate(**payload)


def test_sql_constraints_enforce_metric_comparator_mode_and_household_name(db):
    owner = goal(db)
    for metric, comparator in [("bad", "gte"), ("net_worth", "bad")]:
        with pytest.raises(IntegrityError):
            db.add(models.LifeEventCondition(client_id=1, life_event_id=owner.id, metric=metric, comparator=comparator))
            db.flush()
        db.rollback()
    owner.condition_mode = "bad"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    for _ in range(2):
        db.add(models.HouseholdMember(client_id=1, name="子", birth_date=date(2010, 1, 1)))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_writes_are_client_scoped_and_duplicate_names_are_refused(db):
    owner = goal(db)
    foreign = goal(db, client_id=2)
    with pytest.raises(NotFound):
        conditions.create_condition(db, 2, owner.id, schemas.LifeEventConditionCreate(metric="net_worth", threshold_minor=1))
    with pytest.raises(NotFound):
        add(db, owner, "goal_progress", foreign.id)
    member = household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="本人", birth_date=date(2000, 1, 1)))
    with pytest.raises(NotFound):
        household_service.delete_member(db, 2, member.id)
    with pytest.raises(Conflict):
        household_service.save_member(db, 1, schemas.HouseholdMemberCreate(name="本人", birth_date=date(2000, 1, 1)))


def test_http_crud_evaluation_and_validation(db):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from app.routers.life_events import router
    from app.routers.household_members import router as household_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(household_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    owner = goal(db)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            member = (await client.post('/household-members', json={"name": "子", "birth_date": "2010-10-15"})).json()
            member_id = member["id"]
            assert len((await client.get('/household-members')).json()) == 1
            assert (await client.put(f'/household-members/{member_id}', json={"relation": "長女"})).status_code == 200
            assert (await client.put(f'/household-members/{member_id}', json={"birth_date": None})).status_code == 422
            response = await client.post(f'/life-events/{owner.id}/conditions', json={"metric": "member_age", "threshold_number": 18, "reference_id": member_id})
            assert response.status_code == 200
            condition_id = response.json()["id"]
            assert (await client.get(f'/life-events/{owner.id}/conditions?as_of=2028-10-15')).json()["satisfied"] is True
            assert str(owner.id) in (await client.get('/life-events/conditions')).json()
            assert (await client.put(f'/life-events/{owner.id}', json={"condition_mode": "any"})).status_code == 200
            assert (await client.post(f'/life-events/{owner.id}/conditions', json={"metric": "date_reached", "note": "2030-01-01"})).status_code == 422
            assert (await client.delete(f'/household-members/{member_id}')).status_code == 200
            assert (await client.get(f'/life-events/{owner.id}/conditions')).json()["satisfied"] is None
            app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 2)
            assert (await client.get('/household-members')).json() == []
            assert (await client.delete(f'/life-events/{owner.id}/conditions/{condition_id}')).status_code == 404
            app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
            assert (await client.delete(f'/life-events/{owner.id}/conditions/{condition_id}')).status_code == 200
            assert (await client.get(f'/life-events/{owner.id}/conditions')).json()["conditions"] == []
    async def run_with_wakeups():
        pending = asyncio.create_task(exercise())
        deadline = asyncio.get_running_loop().time() + 30
        while not pending.done() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        if not pending.done():
            pending.cancel()
            pytest.fail("HTTP condition exercise exceeded 30 seconds")
        await pending
    asyncio.run(run_with_wakeups())


def test_large_claim_comparison_does_not_round_through_float(db):
    owner = goal(db)
    _, capsule = finances(db, minor=2**53 + 1)
    add(db, owner, "capsule_claim", capsule.id, comparator="eq", threshold_minor=2**53 + 1)
    assert result(db, owner)["satisfied"] is True


@pytest.mark.parametrize("comparator, as_of, expected", [
    ("gte", date(2030, 4, 1), True), ("gte", date(2030, 3, 31), False),
    ("lte", date(2030, 4, 2), False), ("eq", date(2030, 4, 1), True),
])
def test_date_uses_a_real_date_threshold(db, comparator, as_of, expected):
    owner = goal(db)
    add(db, owner, "date_reached", comparator=comparator, threshold_date=date(2030, 4, 1))
    assert result(db, owner, as_of)["satisfied"] is expected
