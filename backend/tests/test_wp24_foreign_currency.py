"""WP24: money in another currency is kept as it is, and counted at its rate when shown as one amount."""
from datetime import date

from app import models, schemas
from app.domain.journal import Leg
from app.services import capsule_service, goal_service, life_scenario_service as scenarios
from app.services.goal_earmark_service import events_with_progress
from app.services.ledger_service import create_transaction
from scenario_fixtures import account, db  # noqa: F401

TODAY = date.today()


def dollars(db, rate=150.0):
    """A savings account holding 100 USD, 50 of them set aside for a yen earmark of 10,000."""
    if rate:
        db.add(models.ExchangeRate(client_id=1, base_currency="USD", quote_currency="JPY", rate=rate, as_of_date=TODAY))
    savings, income = account(db, "貯蓄"), account(db, "給与", kind="income")
    capsule = models.Capsule(client_id=1, name="旅行", target_amount_minor=10000, monthly_contribution_minor=0,
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=savings.id, target_amount_minor=10000)])
    db.add(capsule)
    db.commit()
    create_transaction(db, client_id=1, date=TODAY, description="入金", amount_minor=10000, currency="USD",
                       from_account_id=income.id, to_account_id=savings.id)
    create_transaction(db, client_id=1, date=TODAY, description="確保", amount_minor=5000, currency="USD",
                       legs=[Leg(savings.id, debit=5000, capsule_id=capsule.id), Leg(savings.id, credit=5000)])
    db.commit()
    return savings, capsule


def test_an_earmark_counts_a_dollar_reservation_toward_its_yen_target(db):
    savings, capsule = dollars(db)
    # The reservation itself stays in dollars; the figure shown is in yen at the day's rate.
    assert capsule_service.claimed_minor(db, 1, capsule.id) == {"USD": 5000}
    assert capsule_service.claimed_value(db, 1, capsule.id) == 7500
    shown = capsule_service.capsule_to_dict(db, capsule)
    assert (shown["current_balance"], shown["progress_pct"]) == (7500, 75.0)
    assert [row["claimed"] for row in capsule_service.list_account_earmarks(db, 1, savings.id)] == [7500]


def test_an_events_funding_and_the_simulation_value_dollars_in_yen(db):
    savings, capsule = dollars(db)
    scenario = models.LifeScenario(client_id=1, name="ゴール", is_goal=True, annual_return=0, inflation=0, horizon_years=1)
    db.add(scenario)
    db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()
    trip = goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(scenario_id=scenario.id, name="旅行", target_amount=10000,
                                                                          target_date=date(TODAY.year + 1, 6, 1)))
    capsule.goal_event_id = trip.id
    db.commit()
    assert {row["name"]: row["current_funded"] for row in events_with_progress(db, 1)}["旅行"] == 7500
    record = models.ScenarioContributionPlan(scenario_id=scenario.id, kind="contribution", account_id=savings.id,
                                             start_period=TODAY.strftime("%Y-%m"), amount_minor=0, interval_months=1, annual_return=0)
    db.add(record)
    db.commit()
    result = scenarios.project(db, 1, scenario)
    # The used account starts at its 100 dollars in yen, as the balance sheet values it.
    assert result["accounts"][0]["p50"][0] == 15000
    assert result["projection"][0]["p50"] == 15000


def test_an_accounts_own_money_stays_exact_beside_converted_foreign_money(db):
    from app.services import life_event_conditions as conditions
    db.add(models.ExchangeRate(client_id=1, base_currency="USD", quote_currency="JPY", rate=1.0, as_of_date=TODAY))
    savings, income = account(db, "貯蓄"), account(db, "給与", kind="income")
    create_transaction(db, client_id=1, date=TODAY, description="大金", amount_minor=2**53 + 1, currency="JPY", from_account_id=income.id, to_account_id=savings.id)
    create_transaction(db, client_id=1, date=TODAY, description="1ドル", amount_minor=100, currency="USD", from_account_id=income.id, to_account_id=savings.id)
    scenario = models.LifeScenario(client_id=1, name="ゴール", is_goal=True)
    db.add(scenario)
    db.commit()
    owner = goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(scenario_id=scenario.id, name="家", target_amount=1, target_date=TODAY))
    db.add(models.LifeEventCondition(client_id=1, life_event_id=owner.id, metric="account_balance", comparator="eq", threshold_minor=2**53 + 2, reference_id=savings.id))
    db.commit()
    assert conditions.evaluate(db, 1, owner.id)["conditions"][0]["satisfied"] is True


def test_without_a_rate_other_money_counts_nothing_as_in_the_balance_sheet(db):
    _, capsule = dollars(db, rate=None)
    assert (capsule_service.claimed_minor(db, 1, capsule.id), capsule_service.claimed_value(db, 1, capsule.id)) == ({"USD": 5000}, 0)
