from scenario_fixtures import goal_scenario_id

from app.services.money_storage import to_minor, rule_amount_fields
from backend.app.domain.journal import Leg

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app import models, schemas
from backend.app.domain.errors import Invalid
from backend.app.database import Base, get_db
from backend.app.dependencies import get_current_client
from backend.app.routers import registry_entries, transaction_batches, transactions
from backend.app.services import (
    capsule_service, fx_service, goal_service, ledger_service,
    registry_service, report_service,
)
from backend.app.services.budget_context import BudgetContext
from backend.app.services.budget_registry_lines import registry_plan_lines
from backend.app.workflows import ai_change_request_workflow as ai, ledger_entry_workflow


@pytest.fixture
def posting():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        client = models.Client(id=1, name="USD client", general_settings={"currency": "USD"})
        other = models.Client(id=2, name="EUR client", general_settings={"currency": "EUR"})
        cash, food, reserve, income = [
            models.Account(client_id=1, name=name, account_type=kind)
            for name, kind in (("cash", "asset"), ("food", "expense"),
                               ("reserve", "asset"), ("income", "income"))
        ]
        db.add_all([client, other, cash, food, reserve, income])
        db.commit()
        app = FastAPI()
        for router in (transactions.router, registry_entries.router,
                       transaction_batches.router):
            app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_client] = lambda: client
        with TestClient(app) as http:
            yield db, client, (cash, food, reserve, income), http
    engine.dispose()


KINDS = ("transaction", "registry")
PATHS = {
    "transaction": "/transactions/",
    "registry": "/auto-transactions/",
}


def _payload(kind, accounts, amount=12.34):
    cash, food, *_ = accounts
    if kind == "transaction":
        return dict(date="2026-10-12", amount=amount, from_account_id=cash.id, to_account_id=food.id)
    return dict(name="Lunch", amount=amount, kind="expense", start_date="2026-10-01", repeat_mode="indefinite", frequency="Monthly",
                source_account_id=cash.id, destination_account_id=food.id, budget_account_id=food.id)



@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("stated,expected", [("omitted", "USD"), (None, "USD"), ("JPY", "JPY"), ("EUR", "EUR")])
def test_http_creation_defaults_only_absent_currency(posting, kind, stated, expected):
    db, _, accounts, http = posting
    payload = _payload(kind, accounts, amount=12 if expected == "JPY" else 12.34)
    if stated != "omitted":
        payload["currency"] = stated
    response = http.post(PATHS[kind], json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["currency"] == expected
    if kind == "transaction":
        tx = db.query(models.Transaction).one()
        assert tx.currency == expected
        assert tx.amount_minor == (12 if expected == "JPY" else 1234)
        assert sum(leg.debit_minor for leg in tx.journal_entries) == tx.amount_minor
        assert sum(leg.credit_minor for leg in tx.journal_entries) == tx.amount_minor
    elif kind in {"registry", "recurring"}:
        assert db.query(models.RegistryEntry).one().currency == expected


@pytest.mark.parametrize("kind", KINDS)
def test_no_setting_uses_get_client_currency_fallback(posting, monkeypatch, kind):
    db, client, accounts, http = posting
    client.general_settings = {}
    db.commit()
    owner = {
        "transaction": ledger_entry_workflow, "recurring": registry_service,
        "registry": registry_service,
    }[kind]
    calls = []

    def resolve(session, client_id):
        calls.append(client_id)
        return fx_service.get_client_currency(session, client_id)

    monkeypatch.setattr(owner, "get_client_currency", resolve)
    response = http.post(PATHS[kind], json=_payload(kind, accounts, amount=12))
    assert response.status_code == 200, response.text
    assert response.json()["currency"] == "JPY"
    assert calls == [client.id]


@pytest.mark.parametrize("operation", ["transaction", "proposal"])
def test_ledger_primitives_use_currency_resolved_by_caller(posting, operation):
    db, client, (cash, food, *_), _ = posting
    columns = dict(date=date(2026, 10, 12), description="Lunch", amount_minor=1234,
                   currency=fx_service.get_client_currency(db, client.id))
    if operation == "transaction":
        row = ledger_service.create_transaction(
            db, client_id=client.id, from_account_id=cash.id, to_account_id=food.id, **columns,
        )
    else:
        row = ledger_service.propose_transaction(
            db, client.id, origin="manual",
            legs=ledger_service.simple_legs(1234, cash.id, food.id), **columns,
        )
    assert (row.currency, row.amount_minor, row.amount) == ("USD", 1234, 12.34)


@pytest.mark.parametrize("operation", ["transaction", "proposal"])
@pytest.mark.parametrize("currency", ["omitted", None])
def test_ledger_rejects_unstated_denomination_without_writing(posting, operation, currency):
    db, client, (cash, food, *_), _ = posting
    columns = dict(date=date(2026, 10, 12), description="Lunch", amount_minor=1234)
    if currency != "omitted":
        columns["currency"] = currency
    message = ("required keyword-only argument: 'currency'" if operation == "proposal" and currency == "omitted"
               else "Caller must state the denomination")
    with pytest.raises(TypeError, match=message):
        if operation == "transaction":
            ledger_service.create_transaction(
                db, client_id=client.id, from_account_id=cash.id, to_account_id=food.id, **columns,
            )
        else:
            ledger_service.propose_transaction(
                db, client.id, origin="manual",
                legs=ledger_service.simple_legs(1234, cash.id, food.id), **columns,
            )
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.TransactionProposal).count() == 0
    assert db.query(models.JournalEntry).count() == 0










def test_capsule_preview_uses_currency_precision_and_required_helper_argument(posting):
    db, client, (cash, food, reserve, _), _ = posting
    capsule = models.Capsule(client_id=client.id, name="Savings", funding_sources=[models.CapsuleFundingSource(client_id=client.id, account_id=reserve.id, target_amount_minor=to_minor(100, "USD") or 0)],
                             target_amount_minor=to_minor(100, "USD"), auto_post=False)
    db.add(capsule)
    db.flush()
    rule = models.CapsuleRule(client_id=client.id, capsule_id=capsule.id, trigger_type="Expense",
                              source_mode="fixed_account", source_account_id=cash.id,
                              amount_type="percentage", **rule_amount_fields(10, "percentage", "USD"), is_active=True)
    db.add(rule)
    db.commit()
    specs = capsule_service.capsule_transfer_specs(
        db, client.id, entries=[schemas.TransactionLeg(account_id=cash.id, credit=12.34),
                               schemas.TransactionLeg(account_id=food.id, debit=12.34)],
        description="Lunch", amount=12.34,
    )
    assert specs[0].amount == 1.23
    assert capsule_service._resolve_rule_amount(rule, 12, currency="JPY") == 1
    with pytest.raises(TypeError, match="currency"):
        capsule_service._resolve_rule_amount(rule, 12.34)




@pytest.mark.parametrize("kind", KINDS)
def test_currency_is_client_scoped_and_not_cached(posting, kind):
    db, client, accounts, http = posting
    if kind == "registry":
        assert fx_service.get_client_currency(db, 2) == "EUR"
    else:
        assert fx_service.get_client_currency(db, 2) == "EUR"
    first = http.post(PATHS[kind], json=_payload(kind, accounts))
    client.general_settings = {"currency": "EUR"}
    db.commit()
    second = http.post(PATHS[kind], json=_payload(kind, accounts))
    assert first.status_code == second.status_code == 200
    assert (first.json()["currency"], second.json()["currency"]) == ("USD", "EUR")


@pytest.mark.parametrize("kind", KINDS)
def test_an_unsupported_setting_is_refused_the_moment_it_is_read(posting, kind):
    """X11: the refusal moved from money storage to the code that resolves it.

    This test used to assert the defect. `normalize_currency` canonicalised
    `" gbp "` to `"GBP"` without validating, so paths failed deep inside money
    storage or persisted an unsupported currency without complaint. Every path
    now refuses in the same place, and nothing is written in any of them.
    """
    db, client, accounts, http = posting
    client.general_settings = {"currency": " gbp "}
    db.commit()
    with pytest.raises(Invalid, match="Unsupported currency 'GBP'"):
        fx_service.normalize_currency(" gbp ")
    with pytest.raises(Invalid, match="Unsupported currency 'GBP'"):
        fx_service.get_client_currency(db, client.id)
    with pytest.raises(Invalid, match="Unsupported currency 'GBP'"):
        http.post(PATHS[kind], json=_payload(kind, accounts))
    assert db.query(models.Transaction).count() == 0


@pytest.mark.parametrize("kind", ["registry"])
def test_update_omission_preserves_existing_currency(posting, kind):
    _, _, accounts, http = posting
    payload = _payload(kind, accounts)
    created = http.post(PATHS[kind], json={**payload, "currency": "EUR"})
    assert created.status_code == 200, created.text
    updated = http.put(PATHS[kind] + str(created.json()["id"]), json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["currency"] == "EUR"


@pytest.mark.parametrize("kind", ["transaction", "registry"])
def test_ai_preview_and_apply_resolve_and_pin_omitted_currency(posting, kind):
    db, client, accounts, _ = posting
    payload = _payload(kind, accounts)
    preview = (ai._preview_transaction_create(db, client.id, payload) if kind == "transaction"
               else ai._preview_automatic_create(db, client.id, payload))
    assert preview["input_payload"]["currency"] == preview["after_snapshot"]["currency"] == "USD"
    client.general_settings = {"currency": "EUR"}
    db.commit()
    row = models.AiChangeRequest(resource="transactions" if kind == "transaction" else "auto_transactions",
                                 action="create", input_payload=preview["input_payload"], risk="medium")
    result = ai._apply_dispatch(db, client.id, row)
    saved = (db.get(models.Transaction, result["transaction_id"]) if kind == "transaction"
             else db.get(models.RegistryEntry, result["registry_entry_id"]))
    assert saved.currency == "USD"
    if kind == "transaction":
        assert saved.amount_minor == 1234


def test_ai_recurring_update_preview_preserves_currency(posting):
    db, client, accounts, _ = posting
    existing = registry_service.create_entry(db, client.id, {**_payload('registry', accounts), 'currency': 'EUR', 'start_date': date(2026, 10, 1), "repeat_mode": "indefinite"})
    preview = ai._preview_automatic_update(db, client.id, {"id": existing.id}, _payload("registry", accounts))
    assert preview["input_payload"]["currency"] == preview["after_snapshot"]["currency"] == "EUR"


@pytest.mark.parametrize("kind", ["transaction", "registry"])
def test_ai_apply_resolves_none_before_creating_legacy_request(posting, kind):
    db, client, accounts, _ = posting
    row = models.AiChangeRequest(resource="transactions" if kind == "transaction" else "auto_transactions",
                                 action="create", input_payload={**_payload(kind, accounts), "currency": None},
                                 risk="medium")
    result = ai._apply_dispatch(db, client.id, row)
    saved = (db.get(models.Transaction, result["transaction_id"]) if kind == "transaction"
             else db.get(models.RegistryEntry, result["registry_entry_id"]))
    assert saved.currency == "USD"
    if kind == "transaction":
        assert saved.amount_minor == 1234


def test_batch_entries_resolve_currency_before_minor_conversion(posting):
    db, _, accounts, http = posting
    response = http.post("/transaction-batches/", json={
        "label": "Lunch", "transactions": [_payload("transaction", accounts)],
    })
    assert response.status_code == 200, response.text
    assert response.json()["transactions"][0]["currency"] == "USD"
    assert db.query(models.Transaction).one().amount_minor == 1234
