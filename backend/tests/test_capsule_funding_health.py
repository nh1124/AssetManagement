"""F3 reports promises that differ from journal facts; it never repairs them."""
import asyncio
from datetime import date
import json

from fastapi import FastAPI
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.domain.journal import Leg
from app.routers import data_transfer as router
from app.services.capsule_service import claimed_minor
from app.services.data_health_service import check_data_health
from app.services.ledger_service import create_transaction


CODES = {
    "account_earmarked_beyond_its_balance": "error",
    "capsule_beyond_its_declared_share": "warning",
    "capsule_claim_outside_the_client_currency": "warning",
    "capsule_plan_does_not_total_its_target": "warning",
    "capsule_funding_account_is_inactive": "warning",
    "capsule_claim_negative_on_account": "warning",
}
BALANCE, SHARE, CURRENCY, PLAN, INACTIVE, NEGATIVE = CODES
WHEN = date(2026, 10, 12)


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool,
                              connect_args={"check_same_thread": False})

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        for client_id, currency in [(1, "JPY"), (2, "USD")]:
            session.add(models.Client(id=client_id, name=f"Client {client_id}",
                                      general_settings={"currency": currency}, ai_config={}))
            session.flush()
            offset = (client_id - 1) * 10
            session.add_all([
                models.Account(id=offset + i, client_id=client_id, name=f"Account {offset + i}",
                               account_type="expense" if i == 4 else "asset", is_active=True)
                for i in [1, 2, 3, 4]
            ])
            session.flush()
            session.add_all([
                models.Capsule(id=offset + i, client_id=client_id, name=f"Capsule {offset + i}",
                               target_amount_minor=1000,
                               monthly_contribution_minor=0)
                for i in [1, 2]
            ])
        session.commit()
        yield session
    engine.dispose()


def post(db, amount, legs, *, currency="JPY", client_id=1):
    result = create_transaction(db, client_id=client_id, date=WHEN, description="Health fixture",
                                amount_minor=amount, currency=currency, legs=legs)
    db.flush()
    return result


def source(db, capsule_id=1, account_id=2, amount=1000, share=None, client_id=1):
    row = models.CapsuleFundingSource(client_id=client_id, capsule_id=capsule_id,
                                      account_id=account_id, target_amount_minor=amount, max_share_bp=share)
    db.add(row)
    db.flush()
    return row


def rule(db, capsule_id=1, account_id=2, client_id=1, **kwargs):
    row = models.CapsuleRule(client_id=client_id, capsule_id=capsule_id,
                            destination_account_id=account_id, trigger_type="Income",
                            amount_type="fixed", amount_minor=1, **kwargs)
    db.add(row)
    db.flush()
    return row


def issues(db, client_id=1):
    return {issue["code"]: issue for issue in check_data_health(db, client_id)["issues"]}


def test_shared_claims_exceed_balance_after_unattributed_spending(db):
    post(db, 10000, [Leg(2, debit=6000, capsule_id=1), Leg(2, debit=4000, capsule_id=2),
                     Leg(1, credit=10000)])
    post(db, 4000, [Leg(4, debit=4000), Leg(2, credit=4000)])
    assert issues(db)[BALANCE]["items"] == [{
        "account_id": 2, "account_name": "Account 2", "currency": "JPY",
        "claimed_total_minor": 10000, "balance_minor": 6000, "excess_minor": 4000,
        "capsules": [{"capsule_id": 1, "name": "Capsule 1", "claimed_minor": 6000},
                     {"capsule_id": 2, "name": "Capsule 2", "claimed_minor": 4000}],
    }]


def test_money_leaves_without_releasing_the_promise(db):
    post(db, 10000, [Leg(2, debit=10000, capsule_id=1), Leg(1, credit=10000)])
    assert issues(db)[BALANCE]["count"] == 0
    # This release of money elsewhere has no capsule attribution.
    post(db, 4000, [Leg(4, debit=4000), Leg(2, credit=4000)])
    assert claimed_minor(db, 1, 1, 2) == {"JPY": 10000}
    item = issues(db)[BALANCE]["items"][0]
    assert (item["claimed_total_minor"], item["balance_minor"], item["excess_minor"]) == (10000, 6000, 4000)


def test_attributed_release_reduces_claim_and_balance_equally(db):
    post(db, 10000, [Leg(2, debit=10000, capsule_id=1), Leg(1, credit=10000)])
    post(db, 4000, [Leg(4, debit=4000), Leg(2, credit=4000, capsule_id=1)])
    assert claimed_minor(db, 1, 1, 2) == {"JPY": 6000}
    assert issues(db)[BALANCE]["count"] == 0


@pytest.mark.parametrize("currency", ["JPY", "USD", "EUR"])
def test_existing_negative_claim_is_reported_per_account_and_currency_without_repair(db, currency):
    post(db, 100, [Leg(2, debit=100, capsule_id=1), Leg(1, credit=100)], currency=currency)
    post(db, 140, [Leg(4, debit=140), Leg(2, credit=140, capsule_id=1)], currency=currency)
    post(db, 200, [Leg(3, debit=200, capsule_id=1), Leg(1, credit=200)], currency=currency)
    post(db, 120, [Leg(2, debit=120, capsule_id=2), Leg(1, credit=120)], currency=currency)
    if currency != "JPY":
        post(db, 100000, [Leg(2, debit=100000, capsule_id=1), Leg(1, credit=100000)])
    db.commit()
    before = snapshot(db)
    issue = issues(db)[NEGATIVE]
    assert issue["severity"] == "warning" and issue["repairable"] is False
    assert issue["count"] == 1
    assert issue["items"] == [{
        "capsule_id": 1, "name": "Capsule 1", "account_id": 2, "account_name": "Account 2",
        "currency": currency, "claimed_minor": -40,
    }]
    assert snapshot(db) == before
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("release", [0, 100])
def test_nonnegative_claims_including_fully_released_claim_are_silent(db, release):
    for currency in ["JPY", "USD"]:
        post(db, 100, [Leg(2, debit=100, capsule_id=1), Leg(1, credit=100)], currency=currency)
        if release:
            post(db, release, [Leg(4, debit=release), Leg(2, credit=release, capsule_id=1)], currency=currency)
    post(db, 50, [Leg(3, debit=50, capsule_id=2), Leg(1, credit=50)])
    assert issues(db)[NEGATIVE]["count"] == 0
    assert issues(db)[NEGATIVE]["items"] == []


def test_claim_exceeds_declared_share_with_exact_figures(db):
    post(db, 10000, [Leg(2, debit=6000, capsule_id=1), Leg(2, debit=4000), Leg(1, credit=10000)])
    source(db, share=5000)
    assert issues(db)[SHARE]["items"] == [{
        "capsule_id": 1, "name": "Capsule 1", "account_id": 2, "account_name": "Account 2",
        "currency": "JPY", "max_share_bp": 5000, "claimed_minor": 6000,
        "allowance_minor": 5000, "balance_minor": 10000,
    }]


@pytest.mark.parametrize("claim,count", [(9, 0), (10, 1)])
def test_share_multiplies_before_integer_division_at_boundary(db, claim, count):
    post(db, 199, [Leg(2, debit=claim, capsule_id=1), Leg(2, debit=199 - claim), Leg(1, credit=199)])
    source(db, share=500)
    issue = issues(db)[SHARE]
    assert issue["count"] == count
    if count:
        assert (issue["items"][0]["claimed_minor"], issue["items"][0]["allowance_minor"]) == (10, 9)


@pytest.mark.parametrize("share,count", [(None, 0), (0, 1), (10000, 0)])
def test_absent_zero_and_full_share_declarations(db, share, count):
    post(db, 10, [Leg(2, debit=10, capsule_id=1), Leg(1, credit=10)])
    source(db, share=share)
    assert issues(db)[SHARE]["count"] == count


def test_foreign_claims_report_each_currency_and_sum_only_matching_accounts(db):
    post(db, 100, [Leg(2, debit=100, capsule_id=1), Leg(1, credit=100)])
    post(db, 12000, [Leg(2, debit=12000, capsule_id=1), Leg(1, credit=12000)], currency="USD")
    post(db, 345, [Leg(3, debit=345, capsule_id=1), Leg(1, credit=345)], currency="USD")
    post(db, 6789, [Leg(2, debit=6789, capsule_id=1), Leg(1, credit=6789)], currency="EUR")
    assert issues(db)[CURRENCY]["items"] == [{
        "capsule_id": 1, "name": "Capsule 1", "client_currency": "JPY",
        "claims_minor": {"EUR": 6789, "USD": 12345},
    }]


def test_client_currency_claim_and_fully_released_foreign_claim_do_not_warn(db):
    post(db, 100, [Leg(2, debit=100, capsule_id=1), Leg(1, credit=100)])
    post(db, 10, [Leg(2, debit=10, capsule_id=1), Leg(1, credit=10)], currency="USD")
    post(db, 10, [Leg(1, debit=10), Leg(2, credit=10, capsule_id=1)], currency="USD")
    assert issues(db)[CURRENCY]["count"] == 0


def test_two_currency_claims_are_checked_against_their_own_holdings(db):
    post(db, 10000, [Leg(2, debit=10000, capsule_id=1), Leg(1, credit=10000)])
    post(db, 12345, [Leg(2, debit=12345, capsule_id=1), Leg(1, credit=12345)], currency="USD")
    post(db, 4000, [Leg(4, debit=4000), Leg(2, credit=4000)])
    source(db, share=10000)
    result = issues(db)
    assert result[BALANCE]["count"] == result[CURRENCY]["count"] == 1
    item = result[BALANCE]["items"][0]
    assert (item["currency"], item["claimed_total_minor"], item["balance_minor"], item["excess_minor"]) == (
        "JPY", 10000, 6000, 4000)
    assert result[CURRENCY]["items"][0]["claims_minor"] == {"USD": 12345}
    assert result[SHARE]["items"][0]["allowance_minor"] == 6000
    # Foreign spending is also checked, solely against the USD balance.
    post(db, 45, [Leg(4, debit=45), Leg(2, credit=45)], currency="USD")
    dollar = next(item for item in issues(db)[BALANCE]["items"] if item["currency"] == "USD")
    assert (dollar["claimed_total_minor"], dollar["balance_minor"], dollar["excess_minor"]) == (12345, 12300, 45)


def test_foreign_balance_does_not_allow_a_client_currency_claim(db):
    post(db, 10, [Leg(2, debit=10, capsule_id=1), Leg(1, credit=10)])
    post(db, 10, [Leg(4, debit=10), Leg(2, credit=10)])
    post(db, 100000, [Leg(2, debit=100000), Leg(1, credit=100000)], currency="USD")
    source(db, share=10000)
    # Even a known FX rate cannot turn those dollars into yen holdings.
    db.add(models.ExchangeRate(client_id=1, base_currency="USD", quote_currency="JPY", rate=150,
                               as_of_date=WHEN))
    db.flush()
    assert issues(db)[BALANCE]["items"][0]["balance_minor"] == 0
    assert issues(db)[SHARE]["items"][0]["allowance_minor"] == 0


@pytest.mark.parametrize("total,difference", [(900, -100), (1100, 100)])
def test_fixed_plan_does_not_total_target(db, total, difference):
    source(db, account_id=2, amount=400)
    source(db, account_id=3, amount=total - 400)
    assert issues(db)[PLAN]["items"] == [{
        "capsule_id": 1, "name": "Capsule 1", "currency": "JPY",
        "planned_total_minor": total, "target_amount_minor": 1000, "difference_minor": difference,
    }]


def test_matching_plan_and_capsule_with_no_plan_do_not_warn(db):
    assert issues(db)[PLAN]["count"] == 0
    source(db, amount=400)
    source(db, account_id=3, amount=600)
    assert issues(db)[PLAN]["count"] == 0
    db.get(models.Capsule, 1).target_amount_minor = 1200
    db.flush()
    assert issues(db)[PLAN]["items"][0]["difference_minor"] == -200


def test_zero_amount_plan_still_counts_as_a_plan(db):
    source(db, amount=0)
    assert issues(db)[PLAN]["items"][0]["difference_minor"] == -1000


@pytest.mark.parametrize("named_by", ["plan", "rule", "both"])
def test_inactive_funding_account_reports_how_it_is_named(db, named_by):
    db.get(models.Account, 2).is_active = False
    if named_by in {"plan", "both"}:
        source(db)
    if named_by in {"rule", "both"}:
        rule(db)
        rule(db)  # Several rules still produce one capsule/account report.
    db.flush()
    assert issues(db)[INACTIVE]["items"] == [{
        "capsule_id": 1, "name": "Capsule 1", "account_id": 2, "account_name": "Account 2",
        "named_by": named_by,
    }]


def test_active_destinations_and_inactive_source_or_legacy_account_do_not_warn(db):
    db.get(models.Account, 2).is_active = False  # Legacy capsule.account_id alone is not a plan.
    source(db, account_id=3)
    rule(db, account_id=3, source_account_id=2)
    assert issues(db)[INACTIVE]["count"] == 0


def seed_violation(db, code, client_id):
    offset = (client_id - 1) * 10
    operating, reserve, other, expense = [offset + i for i in [1, 2, 3, 4]]
    capsule_id = offset + 1
    currency = "JPY" if client_id == 1 else "USD"
    if code in {BALANCE, SHARE}:
        post(db, 100, [Leg(reserve, debit=100, capsule_id=capsule_id), Leg(operating, credit=100)],
             client_id=client_id, currency=currency)
        if code == BALANCE:
            post(db, 40, [Leg(expense, debit=40), Leg(reserve, credit=40)],
                 client_id=client_id, currency=currency)
        else:
            source(db, capsule_id, reserve, share=500, client_id=client_id)
    elif code == CURRENCY:
        post(db, 12345, [Leg(reserve, debit=12345, capsule_id=capsule_id), Leg(operating, credit=12345)],
             client_id=client_id, currency="USD" if currency == "JPY" else "JPY")
    elif code == PLAN:
        source(db, capsule_id, reserve, amount=900, client_id=client_id)
    elif code == INACTIVE:
        db.get(models.Account, reserve).is_active = False
        source(db, capsule_id, reserve, client_id=client_id)
        rule(db, capsule_id, reserve, client_id=client_id)
    elif code == NEGATIVE:
        post(db, 40, [Leg(expense, debit=40), Leg(reserve, credit=40, capsule_id=capsule_id)],
             client_id=client_id, currency=currency)
    db.flush()


@pytest.mark.parametrize("code", CODES)
def test_each_check_is_client_scoped_and_uses_that_clients_currency(db, code):
    seed_violation(db, code, client_id=2)
    assert issues(db, 1)[code]["count"] == 0
    foreign = issues(db, 2)[code]
    assert foreign["count"] == 1
    if code == CURRENCY:
        assert foreign["items"][0]["client_currency"] == "USD"
        assert foreign["items"][0]["claims_minor"] == {"JPY": 12345}
    elif code in {BALANCE, SHARE, PLAN, NEGATIVE}:
        assert foreign["items"][0]["currency"] == "USD"


def test_pending_proposals_and_legacy_caches_are_not_journal_claims(db):
    from app.services.ledger_service import propose_transaction

    source(db, share=0)
    propose_transaction(db, 1, origin="capsule", date=WHEN, description="Not posted",
                        amount_minor=12345, currency="USD", origin_ref={"capsule_id": 1},
                        legs=[Leg(2, debit=12345, capsule_id=1), Leg(1, credit=12345)])
    db.flush()
    result = issues(db)
    assert all(result[code]["count"] == 0 for code in [BALANCE, SHARE, CURRENCY])


def test_every_issue_caps_items_at_100_but_keeps_full_count(db):
    for i in range(101):
        row_id = 1000 + i
        db.add(models.Account(id=row_id, client_id=1, name=f"Reserve {i}", account_type="asset", is_active=False))
        db.flush()
        db.add(models.Capsule(id=row_id, client_id=1, name=f"Goal {i}", target_amount_minor=1000,
                              monthly_contribution_minor=0))
        db.flush()
        source(db, row_id, row_id, amount=1, share=0)
        post(db, 100, [Leg(row_id, debit=100, capsule_id=row_id), Leg(1, credit=100)])
        post(db, 99, [Leg(4, debit=99), Leg(row_id, credit=99)])
        post(db, 1, [Leg(row_id, debit=1, capsule_id=row_id), Leg(1, credit=1)], currency="USD")
        post(db, 1, [Leg(4, debit=1), Leg(row_id, credit=1, capsule_id=row_id)], currency="EUR")
    result = issues(db)
    for code, severity in CODES.items():
        issue = result[code]
        assert set(issue) == {"code", "severity", "title", "detail", "count", "repairable", "items"}
        assert issue["severity"] == severity
        assert issue["repairable"] is False
        assert issue["count"] == 101
        assert len(issue["items"]) == 100


def snapshot(db):
    return {
        table.name: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                           for row in db.execute(sa.select(table)).mappings())
        for table in Base.metadata.sorted_tables
    }


def test_http_health_returns_all_codes_and_counts_without_writes(db, monkeypatch):
    post(db, 10000, [Leg(2, debit=10000, capsule_id=1), Leg(1, credit=10000)])
    post(db, 4000, [Leg(4, debit=4000), Leg(2, credit=4000)])
    post(db, 12345, [Leg(2, debit=12345, capsule_id=1), Leg(1, credit=12345)], currency="USD")
    post(db, 40, [Leg(4, debit=40), Leg(3, credit=40, capsule_id=1)])
    source(db, amount=900, share=500)
    rule(db)
    db.get(models.Account, 2).is_active = False
    db.commit()
    before = snapshot(db)
    test_app = FastAPI()
    test_app.include_router(router.router)
    test_app.dependency_overrides[router.get_db] = lambda: db
    test_app.dependency_overrides[router.get_current_client] = lambda: db.get(models.Client, 1)

    def unexpected(*_args, **_kwargs):
        pytest.fail("GET /data/health must not flush or commit")

    monkeypatch.setattr(db, "flush", unexpected)
    monkeypatch.setattr(db, "commit", unexpected)

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://testserver") as http:
            task = asyncio.create_task(http.get("/data/health"))
            deadline = asyncio.get_running_loop().time() + 30
            while not task.done():
                await asyncio.wait({task}, timeout=0.01)
                if asyncio.get_running_loop().time() >= deadline:
                    task.cancel()
                    pytest.fail("GET /data/health did not complete in 30 seconds")
            return task.result()

    response = asyncio.run(request())
    assert response.status_code == 200
    result = {issue["code"]: issue for issue in response.json()["issues"]}
    for code, severity in CODES.items():
        assert result[code]["count"] == 1
        assert result[code]["severity"] == severity
        assert result[code]["repairable"] is False
    assert snapshot(db) == before
    assert not db.new and not db.dirty and not db.deleted
