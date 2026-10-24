"""WP29: error text follows the language the screen asks for (Accept-Language).

English requests get English, Japanese requests Japanese, and a request that names
no language (the MCP server, scripts) gets every message exactly as written before.
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client, request_language
from app.domain.errors import Invalid, NotFound, Refused
from app.domain.messages import Message, localize, message_of
from app.main import app as main_app
from app.routers import accounts, analysis, depreciations, household_members, life_scenarios, registry_entries

EN = {"Accept-Language": "en"}
JA = {"Accept-Language": "ja"}


@pytest.mark.parametrize("header,expected", [
    ("en", "en"), ("ja", "ja"), ("en-US,en;q=0.9", "en"), ("ja-JP,ja;q=0.9,en;q=0.8", "ja"),
    ("ja;q=0.2, en;q=0.8", "en"), ("fr-FR,en;q=0.5", "en"), ("fr", None), ("*", None), ("", None),
    ("en;q=0", None), ("en;q=abc", None),
])
def test_request_language_reads_accept_language(header, expected):
    request = SimpleNamespace(headers={"accept-language": header} if header else {})
    assert request_language(request) == expected


def test_a_message_is_its_written_text_until_a_language_is_asked_for():
    message = Message("口座が見つかりません。", en="Account not found")
    assert message == "口座が見つかりません。" and str(Invalid(message)) == "口座が見つかりません。"
    assert (message.in_language("en"), message.in_language("ja"), message.in_language(None)) == (
        "Account not found", "口座が見つかりません。", "口座が見つかりません。")
    assert message_of(ValueError(message)) is message
    assert message_of(ValueError("plain")) == "plain"
    assert localize({"a": [message, 1], "b": None}, "en") == {"a": ["Account not found", 1], "b": None}
    error = NotFound("Capsule not found", ja="取り置きが見つかりません。")
    assert str(error) == "Capsule not found" and error.args[0].in_language("ja") == "取り置きが見つかりません。"


@pytest.fixture
def http():
    http_app = FastAPI(exception_handlers=main_app.exception_handlers)

    @http_app.get("/domain/ja-source")
    def ja_source():
        raise Refused("終了月は開始月以降にしてください。", en="The end month must be on or after the start month.", status_code=422)

    @http_app.get("/domain/en-source")
    def en_source():
        raise NotFound("Capsule not found", ja="取り置きが見つかりません。")

    @http_app.get("/domain/payload")
    def payload():
        raise Invalid("x", payload={"code": "c", "reason": Message("理由", en="Reason")})

    @http_app.get("/http")
    def http_exception():
        raise HTTPException(status_code=404, detail=Message("Product not found", ja="物品が見つかりません。"),
                            headers={"X-Kept": "yes"})

    @http_app.get("/value-error")
    def value_error():
        try:
            raise ValueError(Message("Budget plan not found", ja="予算計画が見つかりません。"))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=message_of(exc)) from exc

    @http_app.post("/validation")
    def validation(body: schemas.LifeScenarioName):
        return body

    with TestClient(http_app) as client:
        yield client


@pytest.mark.parametrize("path,status,ja,en,unasked", [
    ("/domain/ja-source", 422, "終了月は開始月以降にしてください。", "The end month must be on or after the start month.",
     "終了月は開始月以降にしてください。"),
    ("/domain/en-source", 404, "取り置きが見つかりません。", "Capsule not found", "Capsule not found"),
    ("/http", 404, "物品が見つかりません。", "Product not found", "Product not found"),
    ("/value-error", 404, "予算計画が見つかりません。", "Budget plan not found", "Budget plan not found"),
])
def test_error_details_follow_the_requested_language(http, path, status, ja, en, unasked):
    for headers, expected in ((EN, en), (JA, ja), ({}, unasked), ({"Accept-Language": "*"}, unasked)):
        response = http.get(path, headers=headers)
        assert (response.status_code, response.json()) == (status, {"detail": expected})


def test_headers_and_payloads_survive_localization(http):
    assert http.get("/http", headers=EN).headers["x-kept"] == "yes"
    assert http.get("/domain/payload", headers=EN).json() == {"detail": {"code": "c", "reason": "Reason"}}
    assert http.get("/domain/payload", headers=JA).json() == {"detail": {"code": "c", "reason": "理由"}}
    assert http.get("/domain/payload").json() == {"detail": {"code": "c", "reason": "理由"}}


def test_schema_validator_messages_follow_the_language_and_pydantic_messages_stay(http):
    def messages(body, headers):
        response = http.post("/validation", json=body, headers=headers)
        assert response.status_code == 422
        return [error["msg"] for error in response.json()["detail"]]

    assert messages({"name": " "}, EN) == ["Enter a scenario name."]
    assert messages({"name": " "}, JA) == ["シナリオ名を入力してください。"]
    assert messages({"name": " "}, {}) == ["Value error, シナリオ名を入力してください。"]
    assert messages({"name": "a", "extra": 1}, EN) == messages({"name": "a", "extra": 1}, {})


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="test", general_settings={"currency": "JPY"}))
    session.add(models.Product(client_id=1, name="机", category="equipment", is_asset=True,
                               purchase_price_minor=50000, purchase_date=date(2026, 1, 1), lifespan_months=24,
                               depreciation_method="none"))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def studio(db):
    http_app = FastAPI(exception_handlers=main_app.exception_handlers)
    for module in (accounts, analysis, depreciations, household_members, life_scenarios, registry_entries):
        http_app.include_router(module.router)
    http_app.dependency_overrides[get_db] = lambda: db
    http_app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
    with TestClient(http_app) as client:
        yield client


def test_studio_routes_answer_in_the_screen_language(studio, db):
    # A router's own 404, a ja-written one, a service refusal and a schema validator.
    cases = [
        (lambda h: studio.get("/accounts/999/earmarks", headers=h), 404,
         "口座・科目が見つかりません。", "Account not found", "Account not found"),
        (lambda h: studio.delete("/auto-transactions/999", headers=h), 404,
         "自動取引が見つかりません", "Automatic transaction not found", "自動取引が見つかりません"),
        (lambda h: studio.post("/household-members", json={"name": " ", "birth_date": "1990-01-01"}, headers=h), 422,
         "名前を入力してください。", "Enter a name.", "名前を入力してください。"),
    ]
    for send, status, ja, en, unasked in cases:
        for headers, expected in ((EN, en), (JA, ja), ({}, unasked)):
            response = send(headers)
            assert (response.status_code, response.json()) == (status, {"detail": expected})
    response = studio.post("/life-scenarios", json={"name": " "}, headers=EN)
    assert response.status_code == 422 and response.json()["detail"][0]["msg"] == "Enter a scenario name."


@pytest.mark.parametrize("read", [
    lambda client, product_id, headers: client.get(
        "/depreciations/preview", params={"product_id": product_id}, headers=headers).json()["blocked_reason"],
    lambda client, product_id, headers: client.get(
        "/analysis/depreciation", headers=headers).json()["items"][0]["blocked_reason"],
], ids=["ledger-form-preview", "fixed-asset-positions"])
def test_depreciation_reasons_follow_the_screen_language(studio, db, read):
    product_id = db.query(models.Product.id).scalar()
    reasons = {language: read(studio, product_id, headers) for language, headers in (("en", EN), ("ja", JA), (None, {}))}
    assert reasons == {"en": "No depreciation method is set", "ja": "減価償却の方法が設定されていません",
                       None: "No depreciation method is set"}


# Literal messages that stay as written, with why. Each count is exact, so a new
# untranslated message fails here and a translated one must shrink its entry.
APP_DIR = Path(__file__).resolve().parents[1] / "app"
DOMAIN_ERRORS = {"DomainError", "NotFound", "Invalid", "Conflict", "Refused", "BatchPostingError"}
UNTRANSLATED: dict[str, int] = {
    # MCP-only: the AI context reads, the MCP token exchange and transaction
    # batches (no screen posts them).
    "services/ai_context_service": 3,
    "routers/auth": 3,
    "routers/transaction_batches": 1,
    "workflows/transaction_batch_workflow": 1,
    # Change requests the AI drafts: an unsupported operation.
    "workflows/ai_change_request_workflow": 1,
    # Data import: the settings screen shows its own message for any failure.
    "services/data_transfer_service": 1,
    # Readiness probe.
    "main": 1,
}


def _untranslated_literals() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        module = path.relative_to(APP_DIR).with_suffix("").as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            call = node.exc
            name = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            if name in DOMAIN_ERRORS:
                # With a payload, the payload is the response body and the message is never sent.
                text = call.args[0] if call.args else None
                literal = isinstance(text, (ast.Constant, ast.JoinedStr)) and not ({"ja", "en", "payload"} & keywords.keys())
            elif name == "HTTPException":
                literal = isinstance(keywords.get("detail"), (ast.Constant, ast.JoinedStr))
            else:
                continue
            if literal:
                counts[module] = counts.get(module, 0) + 1
    return counts


def test_every_literal_error_message_has_both_languages():
    assert _untranslated_literals() == UNTRANSLATED
