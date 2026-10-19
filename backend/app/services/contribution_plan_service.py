"""Own each scenario's 積立設定: per-account monthly contributions and yields over time."""
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
            "annual_return": plan.annual_return, "note": plan.note}


def _get(db: Session, client_id: int, plan_id: int) -> models.ScenarioContributionPlan:
    plan = db.query(models.ScenarioContributionPlan).join(models.LifeScenario).filter(
        models.ScenarioContributionPlan.id == plan_id, models.LifeScenario.client_id == client_id,
    ).first()
    if plan is None:
        raise NotFound("積立設定のレコードが見つかりません。")
    return plan


def _values(db: Session, client_id: int, values: dict) -> dict:
    result = {}
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
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            raise Refused("月額は0以上の数値で指定してください。", status_code=422)
        result["monthly_amount_minor"] = Money.from_major(str(amount), money_client_currency(db, client_id)).minor
    if "annual_return" in values:
        rate = values["annual_return"]
        if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate)):
            raise Refused("年利は有限の数値で指定してください。", status_code=422)
        result["annual_return"] = None if rate is None else float(rate)
    if "note" in values:
        result["note"] = (values["note"] or "").strip() or None
    return result


def _unique(db: Session, scenario_id: int, account_id: int, start_period: str, plan_id: int | None = None) -> None:
    query = db.query(models.ScenarioContributionPlan.id).filter_by(
        scenario_id=scenario_id, account_id=account_id, start_period=start_period)
    if plan_id is not None:
        query = query.filter(models.ScenarioContributionPlan.id != plan_id)
    if query.first():
        raise Conflict("同じ口座・開始月のレコードがあります。")


def create_plan(db: Session, client_id: int, scenario_id: int, values: dict) -> models.ScenarioContributionPlan:
    get_scenario(db, client_id, scenario_id)
    data = _values(db, client_id, {"monthly_amount": 0, **values})
    if "account_id" not in data or "start_period" not in data:
        raise Refused("口座と開始月を指定してください。", status_code=422)
    _unique(db, scenario_id, data["account_id"], data["start_period"])
    plan = models.ScenarioContributionPlan(scenario_id=scenario_id, **data)
    db.add(plan)
    db.commit()
    return plan


def update_plan(db: Session, client_id: int, plan_id: int, values: dict) -> models.ScenarioContributionPlan:
    plan = _get(db, client_id, plan_id)
    data = _values(db, client_id, values)
    _unique(db, plan.scenario_id, data.get("account_id", plan.account_id), data.get("start_period", plan.start_period), plan.id)
    for key, value in data.items():
        setattr(plan, key, value)
    db.commit()
    return plan


def delete_plan(db: Session, client_id: int, plan_id: int) -> None:
    db.delete(_get(db, client_id, plan_id))
    db.commit()


def copy_plans(db: Session, source_id: int, target_id: int) -> None:
    for plan in db.query(models.ScenarioContributionPlan).filter_by(scenario_id=source_id).all():
        db.add(models.ScenarioContributionPlan(
            scenario_id=target_id, account_id=plan.account_id, start_period=plan.start_period,
            monthly_amount_minor=plan.monthly_amount_minor, annual_return=plan.annual_return, note=plan.note,
        ))
    db.flush()


def resolve(plans, account_id: int, period: str, default_rate: float) -> tuple[int, float]:
    """(monthly amount in minor units, annual return %) for an account in a month.

    The latest record starting on or before the month gives the amount; the latest
    such record naming a yield gives the rate, else the scenario's default.
    """
    amount, rate = 0, default_rate
    for plan in sorted((plan for plan in plans if plan.account_id == account_id and plan.start_period <= period),
                       key=lambda plan: plan.start_period):
        amount = plan.monthly_amount_minor
        if plan.annual_return is not None:
            rate = plan.annual_return
    return amount, rate


def monthly_total_minor(plans, period: str, default_rate: float = 0.0) -> int:
    """Everything the scenario puts aside in a month, across its accounts."""
    return sum(resolve(plans, account_id, period, default_rate)[0] for account_id in {plan.account_id for plan in plans})
