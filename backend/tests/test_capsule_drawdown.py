"""R2: journal credits release claims; annotations record their meaning."""
import asyncio
import json
from datetime import date, datetime

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.domain.errors import Invalid, DomainError
from app.domain.journal import Leg
from app.domain.transfer import validate_import_payload
from app.main import domain_error_handler
from app.routers import capsules as router
from app.services import capsule_service as capsule, ledger_service as ledger
from app.services.data_transfer_service import export_client, import_client

WHEN = date(2026, 10, 14)


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"}) for i in [1, 2]])
        session.flush()
        session.add_all([
            models.Account(id=i, client_id=1 if i < 5 else 2, name=f"Account {i}",
                           account_type="expense" if i == 3 else "asset" if i == 4 else "asset")
            for i in range(1, 6)
        ])
        session.add_all([
            models.Capsule(id=i, client_id=i, name=f"Capsule {i}", target_amount_minor=1000,
                           monthly_contribution_minor=0,
                           funding_sources=[models.CapsuleFundingSource(client_id=i, account_id=2 if i == 1 else 5, target_amount_minor=1000)])
            for i in [1, 2]
        ])
        session.flush()
        ledger.create_transaction(session, client_id=1, date=WHEN, description="Reserve",
                                  amount_minor=700, currency="JPY",
                                  legs=[Leg(2, debit=700, capsule_id=1), Leg(1, credit=700)])
        session.commit()
        yield session
    engine.dispose()


def draw(db, **overrides):
    return capsule.record_drawdown(db, **{
        "client_id": 1, "capsule_id": 1, "amount": 125, "from_account_id": 2,
        "to_account_id": 3, "kind": "as_intended", "date": WHEN,
        "description": "Saved for this", "note": "Purpose", **overrides,
    })


@pytest.mark.parametrize("kind", ["as_intended", "diverted"])
@pytest.mark.parametrize("destination", [1, 3, 4])
def test_drawdown_releases_journal_claim_and_records_reason(db, kind, destination):
    tx, row = draw(db, kind=kind, to_account_id=destination)
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 575}
    assert tx.amount_minor == row.amount_minor == 125
    assert tx.currency == "JPY" and tx.date == WHEN
    assert [(entry.account_id, entry.debit_minor, entry.credit_minor, entry.capsule_id)
            for entry in sorted(tx.journal_entries, key=lambda entry: entry.sort_order)] == [
                (destination, 125, 0, None), (2, 0, 125, 1)]
    db.expire_all()
    saved = capsule.list_drawdowns(db, 1, 1)[0]
    assert (saved.kind, saved.transaction_id, saved.note) == (kind, tx.id, "Purpose")
    saved.amount_minor = 999
    db.flush()
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 575}
    db.delete(saved)
    db.commit()
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 575}


@pytest.mark.parametrize("patch, message", [
    ({"capsule_id": 2}, "Capsule not found"),
    ({"capsule_id": 999}, "Capsule not found"),
    ({"from_account_id": 5}, "Account 5 not found"),
    ({"to_account_id": 5}, "Account 5 not found"),
    ({"to_account_id": 999}, "Account 999 not found"),
    ({"from_account_id": 1}, "not a capsule funding source"),
    ({"amount": 701}, "claim of 700 JPY"),
    ({"amount": 0}, "must be positive"),
    ({"amount": -1}, "must be positive"),
    ({"amount": float("nan")}, "finite positive"),
    ({"amount": float("inf")}, "finite positive"),
    ({"kind": "other"}, "as_intended or diverted"),
])
def test_invalid_drawdown_is_refused_before_any_write(db, patch, message):
    with pytest.raises(Invalid, match=message):
        draw(db, **patch)
    assert db.query(models.Transaction).count() == 1
    assert db.query(models.CapsuleDrawdown).count() == 0
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 700}
    assert not db.new and not db.dirty and not db.deleted


def test_claim_limit_uses_only_client_currency(db):
    ledger.create_transaction(db, client_id=1, date=WHEN, description="Foreign earmark",
                              amount_minor=100000, currency="USD",
                              legs=[Leg(2, debit=100000, capsule_id=1), Leg(1, credit=100000)])
    db.commit()
    with pytest.raises(Invalid, match="claim of 700 JPY"):
        draw(db, amount=701)
    draw(db, amount=700)
    assert capsule.claimed_minor(db, 1, 1) == {"USD": 100000}
    assert capsule.claimed_minor(db, 1, 1, account_id=2) == {"USD": 100000}


def seed_second_account_claim(db):
    db.add(models.CapsuleFundingSource(client_id=1, capsule_id=1, account_id=1, target_amount_minor=1000))
    ledger.create_transaction(db, client_id=1, date=WHEN, description="Reserve in another account",
                              amount_minor=1000, currency="JPY",
                              legs=[Leg(1, debit=1000, capsule_id=1), Leg(3, credit=1000)])
    db.commit()


@pytest.mark.parametrize("amount,remaining", [(125, 575), (700, 0)])
def test_drawdown_uses_only_source_account_claim_including_exact_release(db, amount, remaining):
    seed_second_account_claim(db)
    draw(db, amount=amount)
    assert capsule.claimed_minor(db, 1, 1, account_id=2).get("JPY", 0) == remaining
    assert capsule.claimed_minor(db, 1, 1, account_id=1) == {"JPY": 1000}
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 1000 + remaining}


def test_drawdown_cannot_use_other_accounts_claim_and_names_its_limit(db):
    seed_second_account_claim(db)
    with pytest.raises(Invalid) as failure:
        draw(db, amount=701)
    assert str(failure.value) == "Drawdown exceeds the capsule claim of 700 JPY on Account 2"
    assert db.query(models.Transaction).count() == 2
    assert db.query(models.CapsuleDrawdown).count() == 0
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 1700}


def test_drawdown_from_funding_account_without_a_claim_is_refused(db):
    db.add(models.CapsuleFundingSource(client_id=1, capsule_id=1, account_id=1, target_amount_minor=0))
    db.commit()
    with pytest.raises(Invalid, match="claim of 0 JPY on Account 1"):
        draw(db, from_account_id=1)
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 700}


def test_minor_units_follow_client_currency(db):
    db.get(models.Client, 1).general_settings = {"currency": "USD"}
    ledger.create_transaction(db, client_id=1, date=WHEN, description="USD earmark",
                              amount_minor=345, currency="USD",
                              legs=[Leg(2, debit=345, capsule_id=1), Leg(1, credit=345)])
    db.commit()
    tx, row = draw(db, amount=1.25)
    assert tx.currency == "USD" and tx.amount_minor == row.amount_minor == 125
    assert capsule.drawdown_to_dict(row)["amount"] == 1.25
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 700, "USD": 220}


def test_list_is_scoped_and_newest_first(db):
    first = draw(db)[1]
    second = draw(db, kind="diverted")[1]
    stamp = datetime(2026, 10, 14, 1)
    first.created_at = second.created_at = stamp
    db.commit()
    assert [row.id for row in capsule.list_drawdowns(db, 1, 1)] == [second.id, first.id]
    assert capsule.list_drawdowns(db, 2, 2) == []
    with pytest.raises(Invalid):
        capsule.list_drawdowns(db, 2, 1)


def test_transaction_cannot_be_recorded_twice_for_same_capsule(db):
    tx, _ = draw(db)
    db.add(models.CapsuleDrawdown(client_id=1, capsule_id=1, transaction_id=tx.id,
                                 kind="diverted", amount_minor=125))
    with pytest.raises(sa.exc.IntegrityError, match="UNIQUE"):
        db.flush()
    db.rollback()
    assert db.query(models.CapsuleDrawdown).count() == 1


def test_database_refuses_a_third_kind(db):
    tx = draw(db)[0]
    with pytest.raises(sa.exc.IntegrityError, match="ck_capsule_drawdown_kind"):
        db.execute(sa.update(models.CapsuleDrawdown).where(
            models.CapsuleDrawdown.transaction_id == tx.id).values(kind="third"))
    db.rollback()


@pytest.mark.parametrize("parent", ["transaction", "capsule"])
def test_deleting_parent_cascades_drawdown(db, parent):
    tx, row = draw(db)
    assert row.transaction.id == tx.id
    if parent == "transaction":
        ledger.delete_transaction(db, tx)
    else:
        capsule.delete_capsule(db, 1, 1, commit=False)
    db.commit()
    assert db.query(models.CapsuleDrawdown).count() == 0
    if parent == "transaction":
        assert capsule.claimed_minor(db, 1, 1) == {"JPY": 700}
    else:
        assert db.query(models.Transaction).count() == 2


def test_commit_false_keeps_annotation_and_journal_in_same_transaction(db):
    draw(db, commit=False)
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 575}
    assert db.query(models.CapsuleDrawdown).count() == 1
    db.rollback()
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 700}
    assert db.query(models.CapsuleDrawdown).count() == 0


def test_annotation_write_failure_rolls_back_journal(db):
    def refuse_drawdown(*_):
        raise RuntimeError("annotation failed")
    sa.event.listen(models.CapsuleDrawdown, "before_insert", refuse_drawdown)
    try:
        with pytest.raises(RuntimeError, match="annotation failed"):
            draw(db)
    finally:
        sa.event.remove(models.CapsuleDrawdown, "before_insert", refuse_drawdown)
    assert db.query(models.Transaction).count() == 1
    assert db.query(models.CapsuleDrawdown).count() == 0
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 700}


@pytest.mark.parametrize("kind", ["as_intended", "diverted"])
def test_backup_carries_and_restores_drawdowns_with_remapped_ids(db, kind):
    tx, row = draw(db, kind=kind)
    document = json.loads(json.dumps(export_client(db, db.get(models.Client, 1))))
    assert document["version"] == 27
    assert document["manifest"]["counts"]["capsule_drawdowns"] == 1
    exported = document["data"]["capsule_drawdowns"][0]
    assert (exported["kind"], exported["amount_minor"], exported["note"]) == (kind, 125, "Purpose")
    assert validate_import_payload(document["data"], document["version"], document["manifest"])["issues"] == []
    target = db.get(models.Client, 2)
    for _ in range(2):
        import_client(db, target, data=document["data"], version=document["version"], manifest=document["manifest"])
        restored = db.query(models.CapsuleDrawdown).filter_by(client_id=2).one()
        assert restored.capsule_id != row.capsule_id and restored.transaction_id != tx.id
        assert (restored.kind, restored.amount_minor, restored.note) == (kind, 125, "Purpose")
        assert restored.created_at == row.created_at
        assert capsule.claimed_minor(db, 2, restored.capsule_id) == {"JPY": 575}
        assert restored.transaction.description == tx.description
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 575}


@pytest.mark.parametrize("patch, code", [
    ({"capsule_id": 999}, "missing_reference"),
    ({"transaction_id": 999}, "missing_reference"),
    ({"kind": "third"}, "invalid_drawdown_kind"),
    ({"amount_minor": 0}, "invalid_drawdown_amount"),
])
def test_backup_validation_rejects_invalid_annotation(db, patch, code):
    draw(db)
    data = export_client(db, db.get(models.Client, 1))["data"]
    data["capsule_drawdowns"][0].update(patch)
    assert any(issue["code"] == code for issue in validate_import_payload(data)["issues"])


def test_http_both_kinds_use_same_shape_and_list_round_trips(db):
    app = FastAPI()
    app.include_router(router.router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[router.database.get_db] = lambda: db
    app.dependency_overrides[router.dependencies.get_current_client] = lambda: db.get(models.Client, 1)

    async def request(http, method, path, **kwargs):
        task = asyncio.create_task(http.request(method, path, **kwargs))
        deadline = asyncio.get_running_loop().time() + 30
        while not task.done():
            await asyncio.wait({task}, timeout=0.01)
            if asyncio.get_running_loop().time() >= deadline:
                task.cancel()
                pytest.fail(f"{method} {path} did not complete")
        return task.result()

    async def round_trip():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            for kind, destination in [("as_intended", 3), ("diverted", 4)]:
                response = await request(http, "POST", "/capsules/1/drawdown", json={
                    "amount": 125, "from_account_id": 2, "to_account_id": destination,
                    "kind": kind, "date": WHEN.isoformat(), "description": "Purchase",
                })
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["drawdown"]["kind"] == kind
                assert result["drawdown"]["transaction_id"] == result["transaction"]["id"]
                assert [(leg["debit"], leg["credit"], leg["capsule_id"]) for leg in result["transaction"]["legs"]] == [
                    (125, 0, None), (0, 125, 1)]
            response = await request(http, "GET", "/capsules/1/drawdowns")
            assert [row["kind"] for row in response.json()] == ["diverted", "as_intended"]
            assert [row["description"] for row in response.json()] == ["Purchase", "Purchase"]
            assert (await request(http, "GET", "/capsules/2/drawdowns")).status_code == 400
            assert capsule.claimed_minor(db, 1, 1) == {"JPY": 450}
    asyncio.run(round_trip())
