"""F2b: each funding account has its own budget intent and journal claim."""
from datetime import date
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from scenario_fixtures import goal_scenario_id

from app import models, schemas
from app.database import Base
from app.domain.errors import Invalid, Refused
from app.domain.journal import Leg
from app.services import capsule_service, goal_service, ledger_service, report_service
from app.services.budget_actuals import actual_for_plan_line, cash_flow_actual_for_plan_line
from app.services.budget_context import BudgetContext
from app.services.budget_lines import _plan_match_key, line_identity_key, plan_line_identity_key
from app.services.budget_plan_service import get_budget_summary
from app.services.budget_plan_store import create_plan_lines, update_plan_lines

PERIOD = "2026-10"


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=1, name="Budget owner", general_settings={"currency": "JPY"}),
            models.Client(id=2, name="Other owner", general_settings={"currency": "JPY"}),
        ])
        session.flush()
        session.add_all([
            models.Account(id=i, client_id=1 if i < 5 else 2, name=f"Account {i}", account_type="asset")
            for i in range(1, 6)
        ])
        session.add(models.BudgetPlan(id=1, client_id=1, name="Baseline", is_default=True))
        session.add(models.Capsule(id=1, client_id=1, name="Capsule", funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=4, target_amount_minor=30000)],
                                  target_amount_minor=30000, monthly_contribution_minor=1001))
        session.commit()
        yield session
    engine.dispose()


def funding(db, accounts=(2, 3), weights=(1, 2)):
    capsule_service.set_funding_sources(db, 1, 1, [
        schemas.CapsuleFundingSourceInput(account_id=account, target_amount=weight, sort_order=index)
        for index, (account, weight) in enumerate(zip(accounts, weights))
    ])


def rows(db):
    return [line for line in get_budget_summary(db, 1, PERIOD, cash_flow_months=1)["plan_lines"]
            if line["target_type"] == "capsule"]


def payload(account_id=None, amount=334, **extra):
    return dict(plan_id=1, target_period=PERIOD, line_type="allocation", target_type="capsule",
                target_id=1, account_id=account_id, amount=amount, source="capsule",
                cash_treatment="cash", **extra)


def stored(db, account_id, amount_minor, **extra):
    values = payload(account_id)
    values.pop("amount")
    values.update(client_id=1, amount_minor=amount_minor)
    values.update(extra)
    line = models.MonthlyPlanLine(**values)
    db.add(line)
    db.commit()
    return line


def post_claim(db, account_id, amount, *, currency="JPY", when=date(2026, 10, 12)):
    ledger_service.create_transaction(
        db, client_id=1, date=when, description="Capsule claim", amount_minor=amount,
        currency=currency, legs=[Leg(account_id, debit=amount, capsule_id=1), Leg(1, credit=amount)],
    )
    db.commit()


def test_two_accounts_split_uneven_contribution_and_have_distinct_identities(db):
    funding(db)
    result = rows(db)
    assert [(r["account_id"], r["account_name"], r["amount"]) for r in result] == [
        (2, "Account 2", 334), (3, "Account 3", 667),
    ]
    assert sum(r["amount"] for r in result) == 1001
    assert line_identity_key(result[0]) != line_identity_key(result[1])
    assert plan_line_identity_key(result[0]) != plan_line_identity_key(result[1])
    assert _plan_match_key("allocation", "capsule", 2, "Capsule") != _plan_match_key(
        "allocation", "capsule", 3, "Capsule")


def test_allocation_uses_sort_order_then_id_to_break_remainder_ties(db):
    funding(db, accounts=(3, 2), weights=(1, 1))
    sources = capsule_service.list_funding_sources(db, 1, 1)
    for source in sources:
        source.sort_order = 0
    db.commit()
    assert [(r["account_id"], r["amount"]) for r in rows(db)] == [(3, 501), (2, 500)]
    sources[0].sort_order = 1
    db.commit()
    assert [(r["account_id"], r["amount"]) for r in rows(db)] == [(2, 501), (3, 500)]


def test_each_rows_actual_is_its_own_claim_and_cash_flow_remains_monthly(db):
    funding(db)
    post_claim(db, 2, 3000, when=date(2026, 9, 12))
    post_claim(db, 2, 45000, currency="USD")
    result = rows(db)
    assert [r["actual"] for r in result] == [3000, 0]
    ctx = BudgetContext(db, 1)
    assert [cash_flow_actual_for_plan_line(ctx, r, PERIOD) for r in result] == [0, 0]
    assert actual_for_plan_line(ctx, dict(result[0], account_id=None), PERIOD) == 3000
    post_claim(db, 3, 70)
    ctx = BudgetContext(db, 1)
    assert [cash_flow_actual_for_plan_line(ctx, r, PERIOD) for r in result] == [0, 70]


def test_account_claim_accessor_memoises_zero_and_is_keyed_by_account(db):
    funding(db)
    post_claim(db, 2, 3000)
    ctx = BudgetContext(db, 1)
    cap = db.get(models.Capsule, 1)
    with patch("app.services.budget_context.claimed_value", wraps=capsule_service.claimed_value) as claim:
        for _ in range(3):
            assert ctx.capsule_account_balance(cap, 2) == 3000
            assert ctx.capsule_account_balance(cap, 3) == 0
        assert claim.call_count == 2
    assert ctx.capsule_balance(cap) == 3000


def test_minor_unit_split_and_account_actual_use_client_currency(db):
    db.get(models.Client, 1).general_settings = {"currency": "USD"}
    db.commit()
    funding(db)
    post_claim(db, 2, 1234, currency="USD")
    post_claim(db, 2, 3000, currency="JPY")
    result = rows(db)
    assert [r["amount"] for r in result] == [3.34, 6.67]
    assert sum(r["amount"] for r in result) == 10.01
    ctx = BudgetContext(db, 1)
    assert actual_for_plan_line(ctx, result[0], PERIOD) == 12.34
    assert actual_for_plan_line(ctx, result[1], PERIOD) == 0
    assert ctx.capsule_balance(db.get(models.Capsule, 1)) == 12.34


@pytest.mark.parametrize("weight", [30000, 0])
def test_one_source_preserves_the_previous_account_and_amount(db, weight):
    funding(db, accounts=(4,), weights=(weight,))
    result = rows(db)
    assert len(result) == 1
    assert (result[0]["account_id"], result[0]["amount"]) == (4, 1001)


def test_seeded_single_source_and_empty_plan_rows(db):
    result = rows(db)
    assert len(result) == 1
    assert (result[0]["account_id"], result[0]["amount"]) == (4, 1001)
    db.get(models.Capsule, 1).funding_sources = []
    db.commit()
    assert rows(db) == []


def test_stored_row_suppresses_only_its_own_account(db):
    funding(db)
    saved = stored(db, 2, 123)
    result = rows(db)
    assert [(r["account_id"], r["amount"], r["id"]) for r in result] == [
        (2, 123, saved.id), (3, 667, None),
    ]


def test_save_keeps_caller_funding_account(db):
    funding(db)
    result = create_plan_lines(db, 1, [payload(3, 667)])
    assert result[0].account_id == 3
    assert [s.account_id for s in db.get(models.Capsule, 1).funding_sources] == [2, 3]


@pytest.mark.parametrize("account_id", [1, 4, 5, 999])
def test_save_refuses_account_outside_plan_including_foreign(db, account_id):
    funding(db)
    with pytest.raises(Invalid) as error:
        create_plan_lines(db, 1, [payload(account_id)])
    assert str(error.value) == f"Account {account_id} is not a funding account of capsule 1 (Capsule)"
    db.rollback()
    assert db.query(models.MonthlyPlanLine).count() == 0


def test_save_refuses_omitted_account_with_multiple_sources(db):
    funding(db)
    with pytest.raises(Invalid) as error:
        create_plan_lines(db, 1, [payload()])
    assert str(error.value) == "Capsule 1 (Capsule) has several funding accounts; account_id is required"
    db.rollback()
    assert db.query(models.MonthlyPlanLine).count() == 0


def test_save_fills_single_source_and_leaves_empty_plan_unbound(db):
    funding(db, accounts=(3,), weights=(30000,))
    assert create_plan_lines(db, 1, [payload()])[0].account_id == 3
    capsule_service.set_funding_sources(db, 1, 1, [])
    assert create_plan_lines(db, 1, [dict(payload(), target_period="2026-11")])[0].account_id is None


def test_seeded_plan_refuses_other_account(db):
    with pytest.raises(Invalid) as error:
        create_plan_lines(db, 1, [payload(2)])
    assert str(error.value) == "Account 2 is not a funding account of capsule 1 (Capsule)"
    db.rollback()
    assert create_plan_lines(db, 1, [payload(4)])[0].account_id == 4


def test_update_preserves_account_and_validates_explicit_changes(db):
    funding(db)
    line = create_plan_lines(db, 1, [payload(3, 667)])[0]
    assert update_plan_lines(db, 1, [{"id": line.id, "amount": 700}])[0].account_id == 3
    with pytest.raises(Invalid, match="Account 4 is not a funding account"):
        update_plan_lines(db, 1, [{"id": line.id, "account_id": 4}])
    db.rollback()
    with pytest.raises(Invalid, match="has several funding accounts; account_id is required"):
        update_plan_lines(db, 1, [{"id": line.id, "account_id": None}])
    db.rollback()
    assert db.get(models.MonthlyPlanLine, line.id).account_id == 3



@pytest.mark.parametrize("reverse", [False, True])
def test_monthly_contribution_sums_active_rows_in_period_and_plan(db, reverse):
    funding(db)
    stored(db, 2, 9000, target_period="2026-09")
    stored(db, 2, 9000, is_active=False)
    db.add(models.BudgetPlan(id=2, client_id=1, name="Alternative"))
    db.commit()
    stored(db, 2, 9000, plan_id=2)
    batch = [payload(2, 334), payload(3, 667)]
    saved = create_plan_lines(db, 1, list(reversed(batch)) if reverse else batch)
    assert db.get(models.Capsule, 1).monthly_contribution_minor == 1001
    first = next(line for line in saved if line.account_id == 2)
    update_plan_lines(db, 1, [{"id": first.id, "amount": 500}])
    assert db.get(models.Capsule, 1).monthly_contribution_minor == 1167
    update_plan_lines(db, 1, [{"id": line.id, "amount": 10 if line.account_id == 2 else 20} for line in saved])
    assert db.get(models.Capsule, 1).monthly_contribution_minor == 30


@pytest.mark.parametrize("with_stored_row", [False, True])
def test_product_pool_suggestion_splits_and_repeats_capsule_products(db, with_stored_row):
    funding(db)
    db.get(models.Capsule, 1).capsule_type = "product_pool"
    product = models.Product(client_id=1, name="Quarterly filter", category="home",
                             last_unit_price_minor=9000, units_per_purchase=1,
                             frequency_days=90, is_asset=False, funding_capsule_id=1,
                             budget_treatment="reserve_allocation")
    db.add(product)
    db.commit()
    if with_stored_row:
        stored(db, 2, 334)
    result = rows(db)
    assert [r["suggested_amount"] for r in result] == [334, 667]
    assert sum(r["suggested_amount"] for r in result) == 1001
    assert result[0]["suggested_items"] == result[1]["suggested_items"] == [
        {"id": product.id, "name": "Quarterly filter", "amount": 3000, "source": "product_reserve"},
    ]
    assert [r["suggested_status"] for r in result] == ["synced", "synced"]


def test_product_pool_warnings_name_each_plan_account_and_its_share(db):
    funding(db)
    db.get(models.Capsule, 1).capsule_type = "product_pool"
    db.commit()
    stored(db, 2, 100)
    warnings = get_budget_summary(db, 1, PERIOD, cash_flow_months=1)["cash_flow_projection"][0]["setup_warnings"]
    result = [w for w in warnings if w.get("source") == "product_reserve"]
    assert [(w["type"], w["account_id"], w["amount"]) for w in result] == [
        ("product_reserve_diff", 2, 334), ("missing_product_reserve", 3, 667),
    ]




def goal_for_capsule(db):
    goal = models.LifeEvent(scenario_id=goal_scenario_id(db, 1), client_id=1, name="Goal", target_amount_minor=30000,
                            target_date=date(2027, 10, 12), priority=1)
    db.add(goal)
    db.flush()
    db.get(models.Capsule, 1).life_event_id = goal.id
    db.commit()
    return goal.id





def test_a_stored_capsule_row_without_an_account_is_not_joined_by_a_duplicate(db):
    """The regression the suite missed and the live data showed.

    250 stored allocation rows in this user's database are typed "capsule" and
    name no account: they predate the funding plan. Keying the virtual rows by
    (capsule, account) made every one of them miss its stored row, so each
    capsule produced two rows -- twelve capsules became twenty-four -- while
    every fixture here happened to store rows that already named an account.

    A stored row whose capsule has exactly one funding account is given that
    account, so it still stands for the capsule.
    """
    funding(db, accounts=(2,), weights=(1,))
    db.add(models.MonthlyPlanLine(
        client_id=1, plan_id=1, target_period=PERIOD, line_type="allocation",
        target_type="capsule", target_id=1, account_id=None, name="Capsule",
        amount_minor=4000, is_active=True, source="capsule", cash_treatment="cash",
    ))
    db.commit()

    produced = rows(db)
    assert len(produced) == 1
    assert produced[0]["account_id"] == 2
    assert produced[0]["amount"] == 4000
    assert produced[0]["id"] is not None


def test_an_account_less_row_still_covers_a_capsule_funded_from_several(db):
    """With several accounts there is no one account to assign it to.

    So it stands for all of them. Adding per-account rows beside it would
    double the capsule's allocation in the summary, which is the same
    duplication in a different shape.
    """
    funding(db, accounts=(2, 3), weights=(1, 1))
    db.add(models.MonthlyPlanLine(
        client_id=1, plan_id=1, target_period=PERIOD, line_type="allocation",
        target_type="capsule", target_id=1, account_id=None, name="Capsule",
        amount_minor=7000, is_active=True, source="capsule", cash_treatment="cash",
    ))
    db.commit()

    produced = rows(db)
    assert len(produced) == 1
    assert produced[0]["account_id"] is None
    assert produced[0]["amount"] == 7000
