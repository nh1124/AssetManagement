from __future__ import annotations

from app.services.money_storage import to_minor


from datetime import date, datetime
from typing import get_args
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from scenario_fixtures import goal_scenario_id
from backend.app import models, schemas
from backend.app.database import Base
from backend.app.domain.errors import Conflict, Invalid
from backend.app.routers import roadmap, simulation_scenarios
from backend.app.services import milestone_service, simulation_scenario_service as scenarios


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="first", general_settings={}),
        models.Client(id=2, name="second", general_settings={}),
    ])
    session.flush()
    session.add_all([
        models.LifeEvent(scenario_id=goal_scenario_id(session, 1), id=1, client_id=1, name="first goal", target_date=date(2030, 1, 1), target_amount_minor=to_minor(1000, "JPY")),
        models.LifeEvent(scenario_id=goal_scenario_id(session, 2), id=2, client_id=2, name="foreign goal", target_date=date(2030, 1, 1), target_amount_minor=to_minor(1000, "JPY")),
        models.LifeEvent(scenario_id=goal_scenario_id(session, 1), id=3, client_id=1, name="other goal", target_date=date(2030, 1, 1), target_amount_minor=to_minor(1000, "JPY")),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _scenario(life_event_id=1, name="baseline", **kwargs):
    return schemas.SimulationScenarioCreate(
        life_event_id=life_event_id, name=name, annual_return=5, inflation=2, **kwargs,
    )


def _milestone(life_event_id=1, **kwargs):
    return schemas.MilestoneCreate(
        life_event_id=life_event_id, date=date(2027, 1, 1), target_amount=1000, **kwargs,
    )


@pytest.mark.parametrize("life_event_id", [2, 999])
def test_create_scenario_rejects_foreign_or_missing_life_event_with_existing_404(db, life_event_id):
    payload = _scenario(life_event_id)
    with pytest.raises(LookupError, match="^Life event not found$"):
        scenarios.create_scenario(db, 1, payload)
    with pytest.raises(HTTPException) as error:
        simulation_scenarios.create_scenario(payload, db, db.get(models.Client, 1))
    assert (error.value.status_code, error.value.detail) == (404, "Life event not found")
    assert db.query(models.SimulationScenario).count() == 0


def test_duplicate_scenario_name_for_same_client_and_goal_leaves_one_row_and_returns_409(db):
    payload = _scenario()
    scenarios.create_scenario(db, 1, payload)
    detail = "A scenario with that name already exists for this goal"
    with pytest.raises(scenarios.ScenarioNameConflict, match=f"^{detail}$"):
        scenarios.create_scenario(db, 1, payload)
    with pytest.raises(scenarios.ScenarioNameConflict) as error:
        simulation_scenarios.create_scenario(payload, db, db.get(models.Client, 1))
    # test_domain_errors.py pins Conflict to 409 over HTTP.
    assert isinstance(error.value, Conflict)
    assert str(error.value) == detail
    assert db.query(models.SimulationScenario).count() == 1


def test_duplicate_scenario_name_is_scoped_to_client_and_life_event(db):
    scenarios.create_scenario(db, 1, _scenario())
    scenarios.create_scenario(db, 1, _scenario(3))
    foreign = scenarios.create_scenario(db, 2, _scenario(2))
    assert db.query(models.SimulationScenario).count() == 3
    assert scenarios.get_scenario(db, 1, foreign.id) is None
    assert scenarios.get_scenario(db, 2, foreign.id) is foreign


def test_update_and_delete_scenario_return_none_for_unknown_or_foreign_id_without_writes(db, monkeypatch):
    foreign_id = scenarios.create_scenario(db, 2, _scenario(2)).id

    def unexpected_write(*args, **kwargs):
        pytest.fail("A missing scenario must not write or close the transaction")

    monkeypatch.setattr(db, "commit", unexpected_write)
    monkeypatch.setattr(db, "flush", unexpected_write)
    for scenario_id in (999, foreign_id):
        assert scenarios.update_scenario(db, 1, scenario_id, schemas.SimulationScenarioUpdate(name="changed")) is None
        assert scenarios.delete_scenario(db, 1, scenario_id) is None
    assert db.query(models.SimulationScenario).count() == 1
    assert not db.new and not db.dirty and not db.deleted
    assert scenarios.get_scenario(db, 2, foreign_id).name == "baseline"


def test_delete_scenario_returns_readable_deleted_row_after_commit_and_session_close(db):
    saved = scenarios.create_scenario(db, 1, _scenario(
        description="saved parameters", monthly_savings=100,
        contribution_schedule=[{"kind": "monthly", "amount": 100}],
    ))
    expected = schemas.SimulationScenario.model_validate(saved).model_dump()
    deleted = scenarios.delete_scenario(db, 1, saved.id)
    assert deleted is saved
    assert inspect(deleted).detached
    assert db.query(models.SimulationScenario).count() == 0
    db.close()
    assert schemas.SimulationScenario.model_validate(deleted).model_dump() == expected
    assert deleted.client_id == 1


def test_list_scenarios_filters_life_event_and_client_and_orders_created_at_then_id_descending(db):
    oldest = scenarios.create_scenario(db, 1, _scenario(name="oldest"))
    middle = scenarios.create_scenario(db, 1, _scenario(name="middle"))
    latest = scenarios.create_scenario(db, 1, _scenario(name="latest"))
    other = scenarios.create_scenario(db, 1, _scenario(3))
    scenarios.create_scenario(db, 2, _scenario(2))
    oldest.created_at = datetime(2026, 1, 1)
    middle.created_at = latest.created_at = datetime(2026, 2, 1)
    other.created_at = datetime(2026, 3, 1)
    db.commit()
    assert [row.name for row in scenarios.list_scenarios(db, 1, 1)] == ["latest", "middle", "oldest"]
    assert [row.name for row in scenarios.list_scenarios(db, 1)] == ["baseline", "latest", "middle", "oldest"]
    with pytest.raises(LookupError, match="^Life event not found$"):
        scenarios.list_scenarios(db, 1, 2)
    with pytest.raises(HTTPException) as error:
        simulation_scenarios.list_scenarios(2, db, db.get(models.Client, 1))
    assert (error.value.status_code, error.value.detail) == (404, "Life event not found")


def test_update_scenario_preserves_omitted_and_null_fields_and_accepts_zero_and_empty_schedule(db):
    saved = scenarios.create_scenario(db, 1, _scenario(description="keep", monthly_savings=100))
    updated = scenarios.update_scenario(db, 1, saved.id, schemas.SimulationScenarioUpdate(
        name="updated", description=None, annual_return=0, contribution_schedule=[],
    ))
    db.expire_all()
    assert updated is saved
    assert (updated.name, updated.description, updated.monthly_savings, updated.annual_return) == (
        "updated", "keep", 100, 0,
    )
    assert updated.contribution_schedule == []
    assert db.query(models.SimulationScenario).count() == 1


@pytest.mark.parametrize("life_event_id", [2, 999])
def test_compare_scenarios_preserves_life_event_404(db, life_event_id):
    payload = schemas.SimulationScenarioCompareRequest(life_event_id=life_event_id, scenario_ids=[1, 2])
    with pytest.raises(HTTPException) as error:
        simulation_scenarios.compare_scenarios(payload, db, db.get(models.Client, 1))
    assert (error.value.status_code, error.value.detail) == (404, "Life event not found")


def test_compare_scenarios_preserves_scenario_404_and_goal_mismatch_400(db):
    foreign_id = scenarios.create_scenario(db, 2, _scenario(2)).id
    other_id = scenarios.create_scenario(db, 1, _scenario(3)).id
    client = db.get(models.Client, 1)
    for scenario_id, status, detail in (
        (999, 404, "Scenario not found"),
        (foreign_id, 404, "Scenario not found"),
        (other_id, 400, f"Scenario {other_id} does not belong to life_event 1"),
    ):
        payload = schemas.SimulationScenarioCompareRequest(life_event_id=1, scenario_ids=[scenario_id, 999])
        error_type = HTTPException if status == 404 else scenarios.ScenarioGoalMismatch
        with pytest.raises(error_type) as error:
            simulation_scenarios.compare_scenarios(payload, db, client)
        if status == 404:
            assert (error.value.status_code, error.value.detail) == (status, detail)
        else:
            # test_domain_errors.py pins Invalid to 400 over HTTP.
            assert isinstance(error.value, Invalid)
            assert str(error.value) == detail


def test_compare_scenarios_keeps_parameter_delegation_request_order_and_response_shape(db, monkeypatch):
    first = scenarios.create_scenario(db, 1, _scenario(name="first", monthly_savings=10))
    second = scenarios.create_scenario(db, 1, _scenario(name="second", monthly_savings=20))
    db.add_all([
        models.SimulationConfig(client_id=1, volatility=7),
        models.SimulationConfig(client_id=2, volatility=99),
    ])
    db.commit()
    calls = []

    def context(session, client_id, event, **kwargs):
        calls.append(kwargs)
        assert session is db and client_id == 1 and event.id == 1
        return dict(current_funded=100, allocated_monthly_savings=kwargs["monthly_savings"],
                    years_remaining=1.5, effective_return=0, contribution_annual_return=0, inflation_rate=2)

    def monte_carlo(**kwargs):
        assert kwargs["volatility"] == 7 and kwargs["n_simulations"] == 1000
        return dict(percentiles=dict(p10=100, p50=200, p90=300),
                    year_by_year=dict(p10=[100], p50=[200], p90=[300]))

    monkeypatch.setattr(scenarios, "get_goal_simulation_context", context)
    monkeypatch.setattr(scenarios, "run_monte_carlo", monte_carlo)
    monkeypatch.setattr(scenarios, "calculate_goal_probability_monte_carlo", lambda **kwargs: 75)
    payload = schemas.SimulationScenarioCompareRequest(life_event_id=1, scenario_ids=[second.id, first.id])
    result = scenarios.compare_scenarios(db, 1, payload)
    assert [row["scenario_name"] for row in result] == ["second", "first"]
    assert calls == [
        dict(annual_return=5, inflation=2, monthly_savings=amount, contribution_schedule=[], allocation_mode="direct")
        for amount in (20, 10)
    ]
    assert result[0]["deterministic_yearly"] == [
        dict(year=0, end_balance=100), dict(year=1, end_balance=340), dict(year=1.5, end_balance=460),
    ]
    for row in result:
        parsed = schemas.SimulationScenarioCompareItem.model_validate(row)
        assert (parsed.target_amount, parsed.years_remaining, parsed.probability) == (1000, 1.5, 75)


# Existing milestone tests cover simulation math; CRUD lives here to keep the
# wave within its permitted file scope.
@pytest.mark.parametrize("life_event_id", [2, 999])
def test_create_and_reset_milestones_reuse_event_check_and_preserve_404(db, life_event_id):
    client = db.get(models.Client, 1)
    with pytest.raises(LookupError, match="^Life event not found$"):
        milestone_service.create_milestone(db, 1, _milestone(life_event_id))
    # The reset-from-annual route was removed with the old goal UI; creation keeps the 404.
    with pytest.raises(HTTPException) as error:
        roadmap.create_milestone(_milestone(life_event_id), db, client)
    assert (error.value.status_code, error.value.detail) == (404, "Life event not found")
    with pytest.raises(LookupError, match="^Life event not found$"):
        milestone_service.reset_milestones_from_annual_plan(db, 1, life_event_id)
    assert db.query(models.Milestone).count() == 0


@pytest.mark.parametrize("basis", get_args(schemas.MilestoneSimulationRequest.model_fields["basis"].annotation))
@pytest.mark.parametrize("life_event_id", [2, 999])
def test_milestone_preview_missing_goal_is_404_before_computation(db, monkeypatch, basis, life_event_id):
    annual_rows = Mock(wraps=milestone_service.build_default_milestone_rows)
    simulation_context = Mock(wraps=milestone_service.get_goal_simulation_context)
    monkeypatch.setattr(milestone_service, "build_default_milestone_rows", annual_rows)
    monkeypatch.setattr(milestone_service, "get_goal_simulation_context", simulation_context)
    with pytest.raises(HTTPException) as error:
        roadmap.preview_life_event_milestones_from_simulation(
            life_event_id, schemas.MilestoneSimulationRequest(basis=basis),
            db, db.get(models.Client, 1),
        )
    assert (error.value.status_code, error.value.detail) == (404, "Life event not found")
    annual_rows.assert_not_called()
    simulation_context.assert_not_called()


def test_milestone_preview_annual_plan_preserves_existing_goal_result(db):
    milestone_service.create_milestone(db, 1, _milestone())
    inputs = dict(annual_return=0, inflation=0, monthly_savings=100, allocation_mode="direct")
    expected_rows = milestone_service.build_default_milestone_rows(db, 1, 1, **inputs)
    assert expected_rows
    preview = milestone_service.preview_milestones_from_simulation(
        db, 1, 1, basis="annual_plan", interval="quarterly", mode="add", **inputs,
    )
    assert preview == {
        "life_event_id": 1, "basis": "annual_plan", "interval": "quarterly",
        "mode": "add", "existing_count": 1, "items": expected_rows,
    }


def test_create_and_update_milestones_keep_nullable_event_and_patch_semantics(db):
    saved = milestone_service.create_milestone(db, 1, _milestone(None, note="keep"))
    updated = milestone_service.update_milestone(db, 1, saved.id, schemas.MilestoneUpdate(
        note=None, target_amount=0, date=date(2028, 1, 1), is_active_plan=False,
    ))
    db.expire_all()
    assert updated is saved
    assert (updated.client_id, updated.life_event_id, updated.note, updated.source) == (1, None, "keep", "manual")
    assert (updated.target_amount, updated.date, updated.is_active_plan) == (0, date(2028, 1, 1), False)


def test_list_milestones_keeps_client_and_event_filters_date_id_order_and_pagination(db):
    later = milestone_service.create_milestone(db, 1, _milestone())
    earlier = milestone_service.create_milestone(db, 1, _milestone())
    same_date = milestone_service.create_milestone(db, 1, _milestone())
    other = milestone_service.create_milestone(db, 1, _milestone(3))
    unlinked = milestone_service.create_milestone(db, 1, _milestone(None))
    milestone_service.create_milestone(db, 2, _milestone(2))
    earlier.date = same_date.date = date(2026, 1, 1)
    db.commit()
    assert milestone_service.list_milestones(db, 1, life_event_id=1) == [earlier, same_date, later]
    assert milestone_service.list_milestones(db, 1, skip=1, limit=1, life_event_id=1) == [same_date]
    assert milestone_service.list_milestones(db, 1) == [earlier, same_date, later, other, unlinked]


def test_update_and_delete_milestones_return_none_for_unknown_or_foreign_id_without_writes(db, monkeypatch):
    foreign_id = milestone_service.create_milestone(db, 2, _milestone(2)).id

    def unexpected_write(*args, **kwargs):
        pytest.fail("A missing milestone must not write or close the transaction")

    monkeypatch.setattr(db, "commit", unexpected_write)
    monkeypatch.setattr(db, "flush", unexpected_write)
    for milestone_id in (999, foreign_id):
        assert milestone_service.update_milestone(db, 1, milestone_id, schemas.MilestoneUpdate(note="changed")) is None
        assert milestone_service.delete_milestone(db, 1, milestone_id) is None
    assert db.query(models.Milestone).count() == 1
    assert not db.new and not db.dirty and not db.deleted


def test_delete_milestone_returns_readable_deleted_row_after_commit_and_session_close(db):
    saved = milestone_service.create_milestone(db, 1, _milestone(
        note="saved milestone", source_snapshot={"basis": "manual"},
    ))
    expected = schemas.Milestone.model_validate(saved).model_dump()
    deleted = milestone_service.delete_milestone(db, 1, saved.id)
    assert deleted is saved
    assert inspect(deleted).detached
    assert db.query(models.Milestone).count() == 0
    db.close()
    assert schemas.Milestone.model_validate(deleted).model_dump() == expected
    assert deleted.client_id == 1


@pytest.mark.parametrize("kind", ["scenario", "milestone"])
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_crud_with_commit_false_flushes_and_allows_caller_rollback(db, kind, operation):
    if kind == "scenario":
        service, model, payload = scenarios, models.SimulationScenario, _scenario()
        patch = schemas.SimulationScenarioUpdate(name="changed")
        field = "name"
    else:
        service, model, payload = milestone_service, models.Milestone, _milestone(note="baseline")
        patch = schemas.MilestoneUpdate(note="changed")
        field = "note"
    create = getattr(service, f"create_{kind}")
    if operation == "create":
        saved = create(db, 1, payload, commit=False)
        saved_id = saved.id
        assert saved_id is not None and db.query(model).count() == 1
        db.rollback()
        assert db.query(model).count() == 0
    else:
        saved = create(db, 1, payload)
        saved_id = saved.id
        action = getattr(service, f"{operation}_{kind}")
        if operation == "update":
            assert action(db, 1, saved_id, patch, commit=False) is saved
            assert getattr(saved, field) == "changed"
        else:
            assert action(db, 1, saved_id, commit=False) is saved
            assert db.query(model).count() == 0
        db.rollback()
        assert db.query(model).count() == 1
        assert getattr(db.get(model, saved_id), field) == "baseline"
