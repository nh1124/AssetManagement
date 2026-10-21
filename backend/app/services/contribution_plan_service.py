"""Own each scenario's 積立設定 (WP23): contributions into an account (積立), transfers between
accounts (口座振替) and withdrawals toward a life event (ライフイベントへの取り崩し), each once or
on a schedule (every month, every year, every N months; N times or until a month).

Also the scenario's 期間ごとの前提 (§8-11): records that set the default yield and the
inflation for some months, over the scenario's own 前提."""
from __future__ import annotations

import math
import re

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import NotFound, Refused
from ..domain.money import Money
from .life_scenario_scope import get as get_scenario
from .money_storage import money_client_currency

PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KINDS = ("contribution", "transfer", "withdrawal")
SHORTAGE = ("skip", "partial")
# A transfer that cannot go through by default does not happen; a withdrawal takes what is there
# (the event pays the rest from the residual net worth).
DEFAULT_SHORTAGE = {"transfer": "skip", "withdrawal": "partial"}
MAX_INTERVAL_MONTHS = 120
MAX_REPEAT = 1200
# How far an open schedule is followed when nothing else bounds it (100 years).
OPEN_MONTHS = 1200


def period_index(period: str) -> int:
    year, month = (int(part) for part in period.split("-"))
    return year * 12 + month - 1


def index_period(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def list_plans(db: Session, client_id: int, scenario_id: int) -> list[models.ScenarioContributionPlan]:
    get_scenario(db, client_id, scenario_id)
    return db.query(models.ScenarioContributionPlan).filter_by(scenario_id=scenario_id).order_by(
        models.ScenarioContributionPlan.account_id, models.ScenarioContributionPlan.start_period, models.ScenarioContributionPlan.id,
    ).all()


def serialize(db: Session, client_id: int, plan: models.ScenarioContributionPlan) -> dict:
    currency = money_client_currency(db, client_id)
    account = db.get(models.Account, plan.account_id)
    target = db.get(models.Account, plan.to_account_id) if plan.to_account_id else None
    return {"id": plan.id, "scenario_id": plan.scenario_id, "kind": plan.kind,
            "account_id": plan.account_id, "account_name": account.name if account else None,
            "to_account_id": plan.to_account_id, "to_account_name": target.name if target else None,
            "start_period": plan.start_period, "amount": Money(plan.amount_minor, currency).to_float(),
            "interval_months": plan.interval_months, "repeat_count": plan.repeat_count, "end_period": plan.end_period,
            "on_shortage": plan.on_shortage, "annual_return": plan.annual_return, "note": plan.note,
            "life_event_id": plan.life_event_id, "life_event_name": plan.event.name if plan.event is not None else None}


def _get(db: Session, client_id: int, plan_id: int) -> models.ScenarioContributionPlan:
    plan = db.query(models.ScenarioContributionPlan).join(models.LifeScenario).filter(
        models.ScenarioContributionPlan.id == plan_id, models.LifeScenario.client_id == client_id,
    ).first()
    if plan is None:
        raise NotFound("積立設定のレコードが見つかりません。")
    return plan


def _asset(db: Session, client_id: int, account_id) -> int:
    account = db.query(models.Account).filter_by(client_id=client_id, id=account_id).first()
    if account is None or account.account_type != "asset":
        raise Refused("同じクライアントの資産口座を選択してください。", status_code=422)
    return account.id


def _whole(value, low: int, high: int, message: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refused(message, status_code=422)
    return value


def _month(value, message: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not PERIOD.match(value):
        raise Refused(message, status_code=422)
    return value


def _values(db: Session, client_id: int, values: dict) -> dict:
    result = {}
    if "kind" in values:
        if values["kind"] not in KINDS:
            raise Refused("レコードの種類は積立・口座振替・ライフイベントへの取り崩しのいずれかです。", status_code=422)
        result["kind"] = values["kind"]
    if "life_event_id" in values:
        result["life_event_id"] = values["life_event_id"]
    if "account_id" in values:
        result["account_id"] = _asset(db, client_id, values["account_id"])
    if "to_account_id" in values:
        result["to_account_id"] = None if values["to_account_id"] is None else _asset(db, client_id, values["to_account_id"])
    if "start_period" in values:
        if values["start_period"] is None:
            raise Refused("開始月はYYYY-MMで指定してください。", status_code=422)
        result["start_period"] = _month(values["start_period"], "開始月はYYYY-MMで指定してください。")
    if "end_period" in values:
        result["end_period"] = _month(values["end_period"], "終了月はYYYY-MMで指定してください。")
    if "interval_months" in values:
        result["interval_months"] = _whole(values["interval_months"], 1, MAX_INTERVAL_MONTHS, f"間隔は1〜{MAX_INTERVAL_MONTHS}か月で指定してください。")
    if "repeat_count" in values:
        result["repeat_count"] = _whole(values["repeat_count"], 1, MAX_REPEAT, f"回数は1〜{MAX_REPEAT}回で指定してください。")
    if "on_shortage" in values:
        if values["on_shortage"] is not None and values["on_shortage"] not in SHORTAGE:
            raise Refused("不足時の扱いは「取引を発生させない」か「ある分だけで取引する」です。", status_code=422)
        result["on_shortage"] = values["on_shortage"]
    if "amount" in values:
        amount = values["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            raise Refused("金額は0以上の数値で指定してください。", status_code=422)
        result["amount_minor"] = Money.from_major(str(amount), money_client_currency(db, client_id)).minor
    if "annual_return" in values:
        rate = values["annual_return"]
        if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate)):
            raise Refused("年利は有限の数値で指定してください。", status_code=422)
        result["annual_return"] = None if rate is None else float(rate)
    if "note" in values:
        result["note"] = (values["note"] or "").strip() or None
    return result


def _settle(db: Session, client_id: int, plan: models.ScenarioContributionPlan) -> None:
    """Check a record as it will be saved, and clear what its kind does not use."""
    kind = plan.kind or "contribution"
    plan.kind = kind
    if kind == "withdrawal":
        event = db.query(models.LifeEvent).filter_by(id=plan.life_event_id, client_id=client_id).first() if plan.life_event_id else None
        if event is None or event.scenario_id != plan.scenario_id or event.direction != "expense":
            raise Refused("同じシナリオの支出のライフイベントを選んでください。", status_code=422)
    else:
        plan.life_event_id = None
    if kind == "transfer":
        if plan.to_account_id is None or plan.to_account_id == plan.account_id:
            raise Refused("口座振替は振替元と別の振替先の口座を選んでください。", status_code=422)
    else:
        plan.to_account_id = None
    if kind == "contribution":
        plan.on_shortage = None
    else:
        if plan.amount_minor <= 0:
            raise Refused("口座振替・取り崩しは0より大きい金額を入力してください。", status_code=422)
        plan.on_shortage = plan.on_shortage or DEFAULT_SHORTAGE[kind]
        plan.annual_return = None
    if plan.interval_months is None:
        # A record that happens once has no end.
        plan.repeat_count = None
        plan.end_period = None
    if plan.end_period is not None and plan.end_period < plan.start_period:
        raise Refused("終了月は開始月以降にしてください。", status_code=422)


def create_plan(db: Session, client_id: int, scenario_id: int, values: dict) -> models.ScenarioContributionPlan:
    get_scenario(db, client_id, scenario_id)
    # Without a kind, an event makes it a withdrawal and a destination a transfer.
    kind = "withdrawal" if values.get("life_event_id") else "transfer" if values.get("to_account_id") else "contribution"
    data = _values(db, client_id, {"kind": kind, "amount": 0, **values})
    # Unless said otherwise, a 積立 or a 口座振替 happens every month and a withdrawal once.
    data.setdefault("interval_months", None if data["kind"] == "withdrawal" else 1)
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


COPIED = ("kind", "account_id", "to_account_id", "start_period", "amount_minor", "interval_months", "repeat_count",
          "end_period", "on_shortage", "annual_return", "note")


def copy_plans(db: Session, source_id: int, target_id: int, event_map: dict[int, int]) -> None:
    """Copy the records; a withdrawal goes toward the copy of its event."""
    for plan in db.query(models.ScenarioContributionPlan).filter_by(scenario_id=source_id).all():
        db.add(models.ScenarioContributionPlan(
            scenario_id=target_id, **{field: getattr(plan, field) for field in COPIED},
            life_event_id=event_map.get(plan.life_event_id) if plan.life_event_id is not None else None,
        ))
    db.flush()


# 期間ごとの前提 (§8-11).

def list_periods(db: Session, client_id: int, scenario_id: int) -> list[models.ScenarioAssumptionPeriod]:
    get_scenario(db, client_id, scenario_id)
    return db.query(models.ScenarioAssumptionPeriod).filter_by(scenario_id=scenario_id).order_by(
        models.ScenarioAssumptionPeriod.start_period, models.ScenarioAssumptionPeriod.id,
    ).all()


def serialize_period(row: models.ScenarioAssumptionPeriod) -> dict:
    return {"id": row.id, "scenario_id": row.scenario_id, "start_period": row.start_period, "end_period": row.end_period,
            "annual_return": row.annual_return, "inflation": row.inflation, "note": row.note}


def _get_period(db: Session, client_id: int, period_id: int) -> models.ScenarioAssumptionPeriod:
    row = db.query(models.ScenarioAssumptionPeriod).join(models.LifeScenario).filter(
        models.ScenarioAssumptionPeriod.id == period_id, models.LifeScenario.client_id == client_id,
    ).first()
    if row is None:
        raise NotFound("期間ごとの前提のレコードが見つかりません。")
    return row


def _period_values(values: dict) -> dict:
    result = {}
    if "start_period" in values:
        if values["start_period"] is None:
            raise Refused("開始月はYYYY-MMで指定してください。", status_code=422)
        result["start_period"] = _month(values["start_period"], "開始月はYYYY-MMで指定してください。")
    if "end_period" in values:
        result["end_period"] = _month(values["end_period"], "終了月はYYYY-MMで指定してください。")
    for field, label in (("annual_return", "年利"), ("inflation", "インフレ")):
        if field in values:
            value = values[field]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise Refused(f"{label}は有限の数値か空欄で指定してください。", status_code=422)
            result[field] = None if value is None else float(value)
    if "note" in values:
        result["note"] = (values["note"] or "").strip() or None
    return result


def _settle_period(row: models.ScenarioAssumptionPeriod) -> None:
    if row.annual_return is None and row.inflation is None:
        raise Refused("年利かインフレのどちらかを入力してください。", status_code=422)
    if row.end_period is not None and row.end_period < row.start_period:
        raise Refused("終了月は開始月以降にしてください。", status_code=422)


def create_period(db: Session, client_id: int, scenario_id: int, values: dict) -> models.ScenarioAssumptionPeriod:
    get_scenario(db, client_id, scenario_id)
    data = _period_values(values)
    if "start_period" not in data:
        raise Refused("開始月を指定してください。", status_code=422)
    row = models.ScenarioAssumptionPeriod(scenario_id=scenario_id, **data)
    _settle_period(row)
    db.add(row)
    db.commit()
    return row


def update_period(db: Session, client_id: int, period_id: int, values: dict) -> models.ScenarioAssumptionPeriod:
    row = _get_period(db, client_id, period_id)
    data = _period_values(values)
    try:
        with db.no_autoflush:
            for key, value in data.items():
                setattr(row, key, value)
            _settle_period(row)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return row


def delete_period(db: Session, client_id: int, period_id: int) -> None:
    db.delete(_get_period(db, client_id, period_id))
    db.commit()


PERIOD_COPIED = ("start_period", "end_period", "annual_return", "inflation", "note")


def copy_periods(db: Session, source_id: int, target_id: int) -> None:
    for row in db.query(models.ScenarioAssumptionPeriod).filter_by(scenario_id=source_id).all():
        db.add(models.ScenarioAssumptionPeriod(scenario_id=target_id, **{field: getattr(row, field) for field in PERIOD_COPIED}))
    db.flush()


def assumption(periods, period: str, field: str, default: float) -> float:
    """annual_return or inflation in a month: the latest-starting record over the month that sets it, else the default."""
    found, key = default, None
    for row in periods:
        value = getattr(row, field)
        if value is None or row.start_period > period or (row.end_period is not None and row.end_period < period):
            continue
        if key is None or (row.start_period, row.id or 0) > key:
            found, key = value, (row.start_period, row.id or 0)
    return found


# Reading the schedule: these take any objects with the record's attributes.

def of_kind(plans, kind: str) -> list:
    return [plan for plan in plans if (getattr(plan, "kind", None) or "contribution") == kind]


def withdrawals(plans) -> list:
    """The records that withdraw toward a life event."""
    return of_kind(plans, "withdrawal")


def occurrence_indexes(plan, first: int, last: int) -> range:
    """The month indexes in [first, last] the record moves money in."""
    start = period_index(plan.start_period)
    step = plan.interval_months
    if step is None:
        return range(start, start + 1) if first <= start <= last else range(0)
    stop = last
    if plan.end_period is not None:
        stop = min(stop, period_index(plan.end_period))
    if plan.repeat_count is not None:
        stop = min(stop, start + step * (plan.repeat_count - 1))
    begin = start if first <= start else start + step * math.ceil((first - start) / step)
    return range(begin, stop + 1, step) if begin <= stop else range(0)


def occurrences(plan, first: str, last: str) -> list[str]:
    return [index_period(index) for index in occurrence_indexes(plan, period_index(first), period_index(last))]


def total_minor(plan, last: int | None = None) -> int:
    """Everything the record moves, to its end (or `last`, or 100 years for an open schedule)."""
    start = period_index(plan.start_period)
    bound = last if last is not None else start + OPEN_MONTHS
    return plan.amount_minor * len(occurrence_indexes(plan, start, bound))


def event_withdrawals(db: Session, event_ids) -> dict[int, list[models.ScenarioContributionPlan]]:
    """{event_id: its ライフイベントへの取り崩し records}, oldest month first."""
    ids = list(event_ids)
    if not ids:
        return {}
    found: dict[int, list[models.ScenarioContributionPlan]] = {}
    for plan in db.query(models.ScenarioContributionPlan).filter(
            models.ScenarioContributionPlan.kind == "withdrawal", models.ScenarioContributionPlan.life_event_id.in_(ids)).order_by(
            models.ScenarioContributionPlan.start_period, models.ScenarioContributionPlan.id):
        found.setdefault(plan.life_event_id, []).append(plan)
    return found


def used_account_ids(plans) -> set[int]:
    """使用口座: every account a record names."""
    return {plan.account_id for plan in plans} | {plan.to_account_id for plan in plans if getattr(plan, "to_account_id", None)}


def rate(plans, account_id: int, period: str, default_rate: float) -> float:
    """The account's yield in a month: the latest contribution starting by then that names one, else the default."""
    found, start = default_rate, ""
    for plan in of_kind(plans, "contribution"):
        if plan.account_id == account_id and plan.annual_return is not None and start <= plan.start_period <= period:
            found, start = plan.annual_return, plan.start_period
    return found


def moved_minor(plans, kind: str, period: str, *, account_id: int | None = None, to_account_id: int | None = None) -> int:
    """What the records of a kind move in a month, optionally from (account_id) or into (to_account_id) one account."""
    index = period_index(period)
    total = 0
    for plan in of_kind(plans, kind):
        if account_id is not None and plan.account_id != account_id:
            continue
        if to_account_id is not None and plan.to_account_id != to_account_id:
            continue
        if occurrence_indexes(plan, index, index):
            total += plan.amount_minor
    return total


def contributed_minor(plans, account_id: int, period: str) -> int:
    """What the 積立 records put into an account in a month."""
    return moved_minor(plans, "contribution", period, account_id=account_id)


def monthly_total_minor(plans, period: str) -> int:
    """Everything the scenario's 積立 records put aside in a month, across its accounts."""
    return moved_minor(plans, "contribution", period)
