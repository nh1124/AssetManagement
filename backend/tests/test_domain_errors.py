import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.database import get_db
from backend.app.dependencies import get_current_client
from backend.app.domain.errors import Conflict, DomainError, Invalid, NotFound, Refused
from backend.app.main import app
from backend.app.routers import recurring, simulation_scenarios, transaction_batches
from backend.app.services import simulation_scenario_service
from backend.app.services.recurring_service import RecurringNotPostable
from backend.app.services.simulation_scenario_service import ScenarioGoalMismatch, ScenarioNameConflict
from backend.app.workflows.transaction_batch_workflow import BatchPostingError


ERROR_CODES = [(NotFound, 404), (Invalid, 400), (Conflict, 409), (Refused, 403)]
ERROR_TYPES = {error_type.__name__: error_type for error_type in (
    DomainError, NotFound, Invalid, Conflict, Refused,
)}


@pytest.fixture
def http():
    # Use the production registrations without running migrations or posting
    # background transactions against the configured database.
    http_app = FastAPI(exception_handlers=app.exception_handlers)

    @http_app.get("/domain/{error_type}")
    def domain_failure(error_type: str, message: str):
        raise ERROR_TYPES[error_type](message)

    @http_app.get("/explicit/{error_type}")
    def explicit_failure(error_type: str, message: str):
        raise ERROR_TYPES[error_type](message, status_code=422)

    @http_app.get("/http/{status_code}")
    def http_failure(status_code: int, message: str):
        raise HTTPException(status_code=status_code, detail=message)

    @http_app.post("/payload/domain")
    def domain_payload_failure(payload: dict | None = None):
        raise Invalid("Import payload validation failed", payload=payload)

    @http_app.post("/payload/http")
    def http_payload_failure(payload: dict | None = None):
        raise HTTPException(
            status_code=400,
            detail=payload if payload is not None else "Import payload validation failed",
        )

    http_app.include_router(recurring.router)
    http_app.include_router(simulation_scenarios.router)
    http_app.include_router(transaction_batches.router)
    http_app.dependency_overrides[get_db] = lambda: None
    http_app.dependency_overrides[get_current_client] = lambda: SimpleNamespace(id=1)
    with TestClient(http_app) as client:
        yield client


@pytest.mark.parametrize("error_type,status_code", ERROR_CODES)
def test_domain_categories_map_to_existing_http_codes(http, error_type, status_code):
    response = http.get(f"/domain/{error_type.__name__}", params={"message": "refused"})
    assert response.status_code == status_code
    assert response.json() == {"detail": "refused"}


@pytest.mark.parametrize("error_type,status_code", ERROR_CODES)
@pytest.mark.parametrize("message", ["", "資金不足", 'line one\n"quoted" \\ line two'])
def test_domain_response_is_byte_identical_to_http_exception(http, error_type, status_code, message):
    domain = http.get(f"/domain/{error_type.__name__}", params={"message": message})
    equivalent = http.get(f"/http/{status_code}", params={"message": message})
    assert domain.status_code == equivalent.status_code
    assert domain.content == equivalent.content
    assert domain.headers == equivalent.headers


@pytest.mark.parametrize("error_type", ERROR_TYPES.values())
def test_domain_errors_bypass_value_error_catches(error_type):
    error = error_type("refused")
    assert not isinstance(error, ValueError)
    with pytest.raises(error_type) as caught:
        try:
            raise error
        except ValueError:
            pytest.fail("A ValueError adapter would replace the domain status with 400")
    assert caught.value is error


@pytest.mark.parametrize("payload", [
    {"message": "Import payload validation failed", "validation": {"error_count": 1}},
    {},
    None,
])
def test_invalid_payload_response_is_byte_identical_to_http_exception(http, payload):
    body = {"content": json.dumps(payload), "headers": {"Content-Type": "application/json"}}
    domain = http.post("/payload/domain", **body)
    equivalent = http.post("/payload/http", **body)
    assert domain.status_code == equivalent.status_code == 400
    assert domain.content == equivalent.content
    assert domain.headers == equivalent.headers
    assert domain.json() == {"detail": payload if payload is not None else "Import payload validation failed"}


@pytest.mark.parametrize("error_type", [DomainError, Invalid])
def test_explicit_status_preserves_the_goal_422(http, error_type):
    message = "transfer_account_id is required because one or more capsules have a non-zero balance."
    domain = http.get(f"/explicit/{error_type.__name__}", params={"message": message})
    equivalent = http.get("/http/422", params={"message": message})
    assert domain.status_code == equivalent.status_code == 422
    assert domain.content == equivalent.content
    assert domain.headers == equivalent.headers


@pytest.mark.parametrize("error_type,category,status_code,path,payload", [
    (RecurringNotPostable, Conflict, 409, "/recurring/1/process", None),
    (ScenarioNameConflict, Conflict, 409, "/simulation/scenarios", {
        "life_event_id": 1, "name": "baseline", "annual_return": 5, "inflation": 2,
    }),
    (ScenarioGoalMismatch, Invalid, 400, "/simulation/scenarios/compare", {
        "life_event_id": 1, "scenario_ids": [1, 2],
    }),
    (BatchPostingError, Invalid, 400, "/transaction-batches/", {"transactions": []}),
])
def test_existing_errors_reach_the_handler_through_their_routers(
    http, monkeypatch, error_type, category, status_code, path, payload,
):
    assert issubclass(error_type, category)
    message = "existing refusal"

    def refuse(*args, **kwargs):
        raise error_type(message)

    if error_type is RecurringNotPostable:
        monkeypatch.setattr(recurring, "get_for_client", lambda *args: object())
        monkeypatch.setattr(recurring, "process_one", refuse)
    elif error_type is ScenarioNameConflict:
        monkeypatch.setattr(simulation_scenario_service, "create_scenario", refuse)
    elif error_type is ScenarioGoalMismatch:
        monkeypatch.setattr(simulation_scenario_service, "compare_scenarios", refuse)
    else:
        monkeypatch.setattr(transaction_batches, "post_transaction_batch", refuse)

    domain = http.post(path, json=payload)
    equivalent = http.get(f"/http/{status_code}", params={"message": message})
    assert domain.status_code == equivalent.status_code == status_code
    assert domain.content == equivalent.content
    assert domain.headers == equivalent.headers
