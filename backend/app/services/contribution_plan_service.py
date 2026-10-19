"""Own each scenario's 積立設定: per-account monthly contributions or withdrawals and yields over time,
and the one-off withdrawals an account makes for a life event (ライフイベントへの取り崩し)."""
from __future__ import annotations

import math
import re

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused
from ..domain.money import Money
from .life_scenario_scope import get as get_scenario
from .money_storage import money_client_currency

PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def list_plans(db: Session, client_id: int, scenario_id: int) -> list[models.ScenarioContributionPlan]:
    get_scenario(db, client_id, scenario_id)
    return db.query(models.ScenarioContributionPlan).filter_by(scenario_id=scenario_id).order_by(
        models.ScenarioContributionPlan.account_id, models.ScenarioContributionPlan.start_period,
    ).all()


def serialize(db: Session, client_id: int, plan: models.ScenarioContributionPlan) -> dict:
    currency = money_client_currency(db, client_id)
    account = db.get(models.Account, plan.account_id)
    return {"id": plan.id, "scenario_id": plan.scenario_id, "account_id": plan.account_id,
            "account_name": account.name if account else None, "start_period": plan.start_period,
            "monthly_amount": Money(plan.monthly_amount_minor, currency).to_float(),
            "annual_return": plan.annual_return, "note": plan.note,
            "life_event_id": plan.life_event_id, "life_event_name": plan.event.name if plan.event is not None else None}


def _get(db: Session, client_id: int, plan_id: int) -> models.ScenarioContributionPlan:
    plan = db.query(models.ScenarioContributionPlan).join(models.LifeScenario).filter(
        models.ScenarioContributionPlan.id == plan_id, models.LifeScenario.client_id == client_id,
    ).first()
    if plan is None:
        raise NotFound("積立設定のレコードが見つかりません。")
    return plan


def _values(db: Session, client_id: int, values: dict) -> dict:
    result = {}
    if "life_event_id" in values:
        result["life_event_id"] = values["life_event_id"]
    if "account_id" in values:
        account = db.query(models.Account).filter_by(client_id=client_id, id=values["account_id"]).first()
        if account is None or account.account_type != "asset":
            raise Refused("同じクライアントの資産口座を選択してください。", status_code=422)
        result["account_id"] = account.id
    if "start_period" in values:
        if not isinstance(values["start_period"], str) or not PERIOD.match(values["start_period"]):
            raise Refused("開始月はYYYY-MMで指定してください。", status_code=422)
        result["start_period"] = values["start_period"]
    if "monthly_amount" in values:
        amount = values["monthly_amount"]
        # A negative amount withdraws from the account every month (取り崩し).
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise Refused("月額は数値で指定してください。", status_code=422)
        result["monthly_amount_minor"] = Money.from_major(str(amount), money_client_currency(db, client_id)).minor
    if "annual_return" in values:
        rate = values["annual_return"]
        if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate)):
            raise Refused("年利は有限の数値で指定してください。", status_code=422)
        result["annual_return"] = None if rate is None else float(rate)
    if "note" in values:
        result["note"] = (values["note"] or "").strip() or None
    return result


def _settle(db: Session, client_id: int, plan: models.ScenarioContributionPlan) -> None:
    """Check a record as it will be saved; an event record withdraws once for an expense of its scenario."""
    if plan.life_event_id is not None:
        event = db.query(models.LifeEvent).filter_by(id=plan.life_event_id, client_id=client_id).first()
        if event is None or event.scenario_id != plan.scenario_id or event.direction != "expense":
            raise Refused("同じシナリオの支出のライフイベントを選んでください。", status_code=422)
        if plan.monthly_amount_minor >= 0:
            raise Refused("ライフイベントへの取り崩しは、取り崩す金額を入力してください。", status_code=422)
        plan.annual_return = None
    query = db.query(models.ScenarioContributionPlan.id).filter_by(
        scenario_id=plan.scenario_id, account_id=plan.account_id, start_period=plan.start_period, life_event_id=plan.life_event_id)
    if plan.id is not None:
        query = query.filter(models.ScenarioContributionPlan.id != plan.id)
    if query.first():
        raise Conflict("同じ口座・月のレコードがあります。" if plan.life_event_id is None else "同じ口座・月・ライフイベントの取り崩しがあります。")


def create_plan(db: Session, client_id: int, scenario_id: int, values: dict) -> models.ScenarioContributionPlan:
    get_scenario(db, client_id, scenario_id)
    data = _values(db, client_id, {"monthly_amount": 0, **values})
    if "account_id" not in data or "start_period" not in data:
        raise Refused("口座と開始月を指定してください。", status_code=422)
    plan = models.ScenarioContributionPlan(scenario_id=scenario_id, **data)
    _settle(db, client_id, plan)
    db.add(plan)
    db.commit()
    return plan


def update_plan(db: Session, client_id: int, plan_id: int, values: dict) -> models.ScenarioContributionPlan:
    plan = _get(db, client_id, plan_id)
    data = _values(db, client_id, values)
    try:
        with db.no_autoflush:
            for key, value in data.items():
                setattr(plan, key, value)
            _settle(db, client_id, plan)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return plan


def delete_plan(db: Session, client_id: int, plan_id: int) -> None:
    db.delete(_get(db, client_id, plan_id))
    db.commit()


def copy_plans(db: Session, source_id: int, target_id: int, event_map: dict[int, int]) -> None:
    """Copy the records; an event record withdraws for the copy of its event."""
    for plan in db.query(models.ScenarioContributionPlan).filter_by(scenario_id=source_id).all():
        db.add(models.ScenarioContributionPlan(
            scenario_id=target_id, account_id=plan.account_id, start_period=plan.start_period,
            monthly_amount_minor=plan.monthly_amount_minor, annual_return=plan.annual_return, note=plan.note,
            life_event_id=event_map.get(plan.life_event_id) if plan.life_event_id is not None else None,
        ))
    db.flush()


def withdrawals(plans) -> list:
    """The records that withdraw once for a life event."""
    return [plan for plan in plans if getattr(plan, "life_event_id", None) is not None]


def event_withdrawals(db: Session, event_ids) -> dict[int, list[models.ScenarioContributionPlan]]:
    """{event_id: its ライフイベントへの取り崩し records}, oldest month first."""
    ids = list(event_ids)
    if not ids:
        return {}
    found: dict[int, list[models.ScenarioContributionPlan]] = {}
    for plan in db.query(models.ScenarioContributionPlan).filter(models.ScenarioContributionPlan.life_event_id.in_(ids)).order_by(
            models.ScenarioContributionPlan.start_period, models.ScenarioContributionPlan.id):
        found.setdefault(plan.life_event_id, []).append(plan)
    return found


def resolve(plans, account_id: int, period: str, default_rate: float) -> tuple[int, float]:
    """(monthly amount in minor units, annual return %) for an account in a month.

    The latest record starting on or before the month gives the amount; the latest
    such record naming a yield gives the rate, else the scenario's default.
    """
    amount, rate = 0, default_rate
    # A withdrawal for a life event happens once; it does not set the monthly amount.
    for plan in sorted((plan for plan in plans if plan.account_id == account_id and plan.start_period <= period
                        and getattr(plan, "life_event_id", None) is None),
                       key=lambda plan: plan.start_period):
        amount = plan.monthly_amount_minor
        if plan.annual_return is not None:
            rate = plan.annual_return
    return amount, rate


def monthly_total_minor(plans, period: str, default_rate: float = 0.0) -> int:
    """Everything the scenario puts aside in a month, across its accounts."""
    return sum(resolve(plans, account_id, period, default_rate)[0] for account_id in {plan.account_id for plan in plans})
