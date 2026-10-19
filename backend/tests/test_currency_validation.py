"""X11: an unsupported currency is refused where it is written, not where it is used.

`normalize_currency` used to canonicalise without validating, so `" gbp "`
became `"GBP"` and travelled into a client's settings. Nothing complained
until some later read built a `Money` from it, which is a long way from the
request that set it. These tests hold the two halves apart: the rule lives in
the domain, and each boundary that accepts a currency states it as a refusal.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.database import Base, get_db
from backend.app.dependencies import get_current_client
from backend.app.domain.errors import DomainError, Invalid, detail_for, status_for
from backend.app.domain.money import normalize_currency
from backend.app.models.money import settings_currency
from backend.app.routers import clients, exchange_rates
from backend.app.services import fx_service
from backend.app.services.client_settings_service import merge_general_settings


@pytest.fixture
def http():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        client = models.Client(id=1, name="Guard", username="guard",
                               general_settings={"currency": "JPY"})
        db.add(client)
        db.commit()
        app = FastAPI()
        app.include_router(clients.router)
        app.include_router(exchange_rates.router)

        @app.exception_handler(DomainError)
        async def _domain(request, exc):
            return await http_exception_handler(
                request, StarletteHTTPException(status_for(exc), detail_for(exc)),
            )

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_client] = lambda: client
        with TestClient(app) as test_client:
            yield db, client, test_client
    engine.dispose()


SUPPORTED = ("JPY", "USD", "EUR")


@pytest.mark.parametrize("code", SUPPORTED)
@pytest.mark.parametrize("shape", ("{}", " {} ", "\t{}\n"))
def test_a_supported_code_is_canonicalised(code, shape):
    assert normalize_currency(shape.format(code.lower())) == code
    assert normalize_currency(shape.format(code.upper())) == code


@pytest.mark.parametrize("absent", (None, "", "   "))
def test_an_absent_code_falls_back_to_the_default(absent):
    # Cur1 decided that an unset preference means the default, not an error.
    assert normalize_currency(absent) == "JPY"
    assert normalize_currency(absent, default="USD") == "USD"


@pytest.mark.parametrize("unsupported", ("GBP", " gbp ", "gbp", "JPYY", "123", "¥"))
def test_an_unsupported_code_is_refused_by_the_domain(unsupported):
    with pytest.raises(ValueError, match="Unsupported currency"):
        normalize_currency(unsupported)


def test_the_service_turns_the_refusal_into_a_bad_request():
    # The domain states the rule; the service is what HTTP can see.
    assert fx_service.normalize_currency(" usd ") == "USD"
    with pytest.raises(Invalid) as error:
        fx_service.normalize_currency(" gbp ")
    assert status_for(error.value) == 400
    assert "GBP" in str(error.value)


def test_a_stored_setting_that_is_unsupported_is_not_silently_accepted(http):
    db, client, _ = http
    client.general_settings = {"currency": "GBP"}
    db.flush()
    with pytest.raises(ValueError, match="Unsupported currency"):
        settings_currency(client.general_settings)
    with pytest.raises(Invalid):
        fx_service.get_client_currency(db, client.id)


def test_setting_a_currency_canonicalises_it(http):
    db, client, test_client = http
    response = test_client.put("/clients/1/settings", json={"general_settings": {"currency": " usd "}})
    assert response.status_code == 200
    assert response.json()["currency"] == "USD"
    db.refresh(client)
    assert client.general_settings["currency"] == "USD"


def test_setting_an_unsupported_currency_is_refused_and_changes_nothing(http):
    db, client, test_client = http
    response = test_client.put(
        "/clients/1/settings",
        json={"general_settings": {"currency": "gbp", "locale": "en-GB"}},
    )
    assert response.status_code == 400
    assert "GBP" in response.json()["detail"]
    db.refresh(client)
    # The whole patch is refused: a rejected currency must not let the rest of
    # the patch land, or the client ends up half-configured.
    assert client.general_settings == {"currency": "JPY"}


def test_merging_settings_without_a_currency_leaves_the_stored_one_alone(http):
    db, client, _ = http
    merged = merge_general_settings(db, client, {"locale": "ja-JP"})
    assert merged == {"currency": "JPY", "locale": "ja-JP"}
