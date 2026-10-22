"""Report a plan's assumptions; evaluation never changes its events or projection."""
from datetime import date
from operator import eq, ge, le

import numpy as np
from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import NotFound
from ..domain.money import Money
from .analysis_service import calculate_logical_balance
from .reporting_service import get_balance_sheet
from .capsule_service import claimed_value_minor
from .fx_service import get_client_currency
from .ledger_valuation import calculate_account_balances
from .goal_earmark_service import events_with_progress
from .goal_service import goal_events_query

REFERENCE_MODELS = {
    "account_balance": models.Account,
    "capsule_claim": models.Capsule,
    "goal_progress": models.LifeEvent,
    "member_age": models.HouseholdMember,
}
COMPARATORS = {"gte": ge, "lte": le, "eq": eq}
MONEY_METRICS = {"net_worth", "free_cash", "account_balance", "capsule_claim"}


def copy_conditions(db: Session, client_id: int, event_map: dict[int, int]) -> None:
    for source in db.query(models.LifeEventCondition).filter(
        models.LifeEventCondition.client_id == client_id, models.LifeEventCondition.life_event_id.in_(event_map),
    ).order_by(models.LifeEventCondition.id):
        values = {column.name: getattr(source, column.name) for column in models.LifeEventCondition.__table__.columns
                  if column.name not in {"id", "life_event_id"}}
        # A condition referring to another copied event follows that story's event.
        if source.metric == "goal_progress":
            values["reference_id"] = event_map.get(source.reference_id, source.reference_id)
        db.add(models.LifeEventCondition(**values, life_event_id=event_map[source.life_event_id]))
    db.flush()


def _event(db: Session, client_id: int, event_id: int) -> models.LifeEvent:
    value = db.query(models.LifeEvent).filter_by(client_id=client_id, id=event_id).first()
    if value is None:
        raise NotFound("ゴールが見つかりません。", en="Life event not found.")
    return value


def create_condition(db: Session, client_id: int, event_id: int, payload: schemas.LifeEventConditionCreate) -> models.LifeEventCondition:
    _event(db, client_id, event_id)
    model = REFERENCE_MODELS.get(payload.metric)
    if model is not None and db.query(model).filter_by(client_id=client_id, id=payload.reference_id).first() is None:
        raise NotFound("同じクライアントの対象を選択してください。", en="Choose a target of this client.")
    row = models.LifeEventCondition(client_id=client_id, life_event_id=event_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_condition(db: Session, client_id: int, event_id: int, condition_id: int,
                     payload: schemas.LifeEventConditionCreate) -> models.LifeEventCondition:
    _event(db, client_id, event_id)
    row = db.query(models.LifeEventCondition).filter_by(client_id=client_id, life_event_id=event_id, id=condition_id).first()
    if row is None:
        raise NotFound("条件が見つかりません。", en="Precondition not found.")
    model = REFERENCE_MODELS.get(payload.metric)
    if model is not None and db.query(model).filter_by(client_id=client_id, id=payload.reference_id).first() is None:
        raise NotFound("同じクライアントの対象を選択してください。", en="Choose a target of this client.")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def delete_condition(db: Session, client_id: int, event_id: int, condition_id: int) -> None:
    _event(db, client_id, event_id)
    row = db.query(models.LifeEventCondition).filter_by(client_id=client_id, life_event_id=event_id, id=condition_id).first()
    if row is None:
        raise NotFound("条件が見つかりません。", en="Precondition not found.")
    db.delete(row)
    db.commit()


def _combine(mode: str, conditions: list[dict]) -> bool | None:
    values = [row["satisfied"] for row in conditions]
    if not values:
        return None
    # Unknown information cannot prove failure; a decisive sibling still settles all/any.
    decisive = False if mode == "all" else True
    if decisive in values:
        return decisive
    if None in values:
        return None
    return not decisive


class _Readers:
    def __init__(self, db: Session, client_id: int, conditions: list[models.LifeEventCondition], as_of: date):
        self.db, self.client_id, self.as_of = db, client_id, as_of
        self.currency = get_client_currency(db, client_id)
        self.references = {
            # A current goal-progress fact always refers to the adopted plan, even in a draft's conditions.
            metric: {row.id: row for row in (
                goal_events_query(db, client_id) if metric == "goal_progress"
                else db.query(model).filter(model.client_id == client_id)
            ).all()}
            for metric, model in REFERENCE_MODELS.items()
            if metric in {row.metric for row in conditions}
        }
        self.figures: dict[tuple[str, int | None], tuple[float | int | date | None, str | None]] = {}
        self.accounts = db.query(models.Account).filter_by(client_id=client_id).all() if {row.metric for row in conditions} & {"net_worth", "free_cash", "account_balance"} else []
        self.balances = calculate_account_balances(db, self.accounts)
        self.actual_minor: dict[tuple[str, int | None], int] = {}
        self.progress: dict[int, dict] | None = None

    def valued(self, key: tuple[str, int | None], minor: int) -> float:
        """An amount in the client's currency, kept in minor units for exact comparisons."""
        self.actual_minor[key] = minor
        return Money(minor, self.currency).to_float()

    def account_minor(self, account_id: int) -> int:
        """An account's balance in the client's currency: its own money exactly, other currencies at their rates."""
        held = self.balances[account_id]
        return held.balances_minor.get(self.currency, 0) + Money.from_major(str(round(held.foreign, 6)), self.currency).minor

    def actual(self, row: models.LifeEventCondition) -> tuple[float | int | date | None, str | None]:
        key = row.metric, row.reference_id
        if key in self.figures:
            return self.figures[key]
        reference = self.references.get(row.metric, {}).get(row.reference_id)
        if row.metric in REFERENCE_MODELS and reference is None:
            return None, "対象が削除されたか、見つかりません。"
        actual, reason = None, None
        # Amounts in other currencies count at their rates, as the balance sheet values them (WP24).
        if row.metric in {"net_worth", "free_cash"}:
            actual = get_balance_sheet(self.db, client_id=self.client_id)["net_worth"] if row.metric == "net_worth" else calculate_logical_balance(self.db, self.client_id)
        elif row.metric == "account_balance":
            actual = self.valued(key, self.account_minor(reference.id))
        elif row.metric == "capsule_claim":
            actual = self.valued(key, claimed_value_minor(self.db, self.client_id, reference.id))
        elif row.metric == "goal_progress":
            if reference.direction != "expense":
                return None, "支出イベントにだけ積立進捗があります。"
            if self.progress is None:
                self.progress = {event["id"]: event for event in events_with_progress(self.db, self.client_id)}
            actual = self.progress[reference.id]["progress_percentage"] if reference.id in self.progress else None
            reason = None if actual is not None else "ゴールのシナリオのイベントではありません。"
        elif row.metric == "member_age":
            born = reference.birth_date
            if born > self.as_of:
                reason = "評価日は生年月日より前です。"
            else:
                actual = self.as_of.year - born.year - ((self.as_of.month, self.as_of.day) < (born.month, born.day))
        elif row.metric == "date_reached":
            actual = self.as_of
        self.figures[key] = actual, reason
        return actual, reason

    def evaluate(self, row: models.LifeEventCondition) -> dict:
        actual, reason = self.actual(row)
        return self.evaluate_actual(row, actual, reason)

    def evaluate_actual(self, row: models.LifeEventCondition, actual, reason: str | None) -> dict:
        threshold = row.threshold_date if row.metric == "date_reached" else row.threshold_number
        if row.metric in MONEY_METRICS:
            threshold = Money(row.threshold_minor, self.currency).to_float() if row.threshold_minor is not None else None
        satisfied = None
        if threshold is None:
            reason = reason or "条件値が指定されていません。"
        elif actual is not None:
            # Compare money as integers, including currencies whose minor unit is not a yen.
            left, right = actual, threshold
            if row.metric in MONEY_METRICS:
                left = self.actual_minor[key] if (key := (row.metric, row.reference_id)) in self.actual_minor else Money.from_major(str(actual), self.currency).minor
                right = row.threshold_minor
            satisfied = COMPARATORS[row.comparator](left, right)
        reference = self.references.get(row.metric, {}).get(row.reference_id)
        return {"id": row.id, "metric": row.metric, "comparator": row.comparator,
                "threshold": threshold, "reference_id": row.reference_id,
                "reference_name": reference.name if reference else None,
                "actual": actual, "satisfied": satisfied, "reason": reason, "note": row.note}


def _evaluate(db: Session, client_id: int, events: list[models.LifeEvent], as_of: date | None) -> dict[int, dict]:
    conditions = db.query(models.LifeEventCondition).filter(
        models.LifeEventCondition.client_id == client_id,
        models.LifeEventCondition.life_event_id.in_([event.id for event in events]),
    ).order_by(models.LifeEventCondition.id).all()
    # as_of sets the calendar facts. Financial metrics use their existing current readers;
    # this wave does not pretend to reconstruct historical plans or project assumptions.
    readers = _Readers(db, client_id, conditions, as_of or date.today())
    grouped: dict[int, list[dict]] = {}
    for condition in conditions:
        grouped.setdefault(condition.life_event_id, []).append(readers.evaluate(condition))
    return {event.id: {"mode": event.condition_mode, "satisfied": _combine(event.condition_mode, grouped.get(event.id, [])),
                       "conditions": grouped.get(event.id, [])} for event in events}


def evaluate(db: Session, client_id: int, life_event_id: int, *, as_of: date | None = None) -> dict:
    with db.no_autoflush:
        event = _event(db, client_id, life_event_id)
        return _evaluate(db, client_id, [event], as_of)[event.id]


def evaluate_all(db: Session, client_id: int, *, as_of: date | None = None) -> dict[int, dict]:
    with db.no_autoflush:
        return _evaluate(db, client_id, goal_events_query(db, client_id).order_by(models.LifeEvent.id).all(), as_of)


def _probability(truth: np.ndarray) -> float | None:
    return None if np.any(truth == 0) else float(np.mean(truth == 1))


class PathJudge:
    """Judge an event's preconditions on simulated paths, at the moment the event would happen.

    Net worth and the balances of simulated accounts are read per path; age and date
    from the event's date; the other metrics (free cash, an earmark's claim, goal
    progress, an account outside the simulation) from today's values.
    """
    PROJECTED = {"net_worth", "member_age", "date_reached"}

    def __init__(self, db: Session, client_id: int, event_ids: list[int]):
        self.db, self.client_id = db, client_id
        rows = db.query(models.LifeEvent).filter(
            models.LifeEvent.client_id == client_id, models.LifeEvent.id.in_(event_ids)).all()
        self.modes = {row.id: row.condition_mode for row in rows}
        conditions = db.query(models.LifeEventCondition).filter(
            models.LifeEventCondition.client_id == client_id,
            models.LifeEventCondition.life_event_id.in_(event_ids),
        ).order_by(models.LifeEventCondition.id).all()
        self.grouped: dict[int, list[models.LifeEventCondition]] = {}
        for condition in conditions:
            self.grouped.setdefault(condition.life_event_id, []).append(condition)
        self.current = _Readers(db, client_id, [row for row in conditions if row.metric not in self.PROJECTED], date.today())

    def has_conditions(self, event_id: int) -> bool:
        return bool(self.grouped.get(event_id))

    def judge(self, event_id: int, at: date | None, net_worth: np.ndarray,
              balances: dict[int, np.ndarray]) -> tuple[np.ndarray, list[dict]]:
        """(truth per path: 1 true, 0 unknown, -1 false; the condition details)."""
        conditions = self.grouped.get(event_id, [])
        paths = net_worth.shape[0]
        if not conditions:
            return np.ones(paths, dtype=np.int8), []
        calendar = _Readers(self.db, self.client_id, [row for row in conditions if row.metric in {"member_age", "date_reached"}],
                            at or date.today())
        truths, details = [], []
        for condition in conditions:
            values = None
            if condition.metric == "net_worth":
                values = net_worth
            elif condition.metric == "account_balance" and condition.reference_id in balances:
                values = balances[condition.reference_id]
            if values is not None:
                median = float(np.median(values))
                detail = self.current.evaluate_actual(condition, median, None)
                truth = np.full(paths, 0, dtype=np.int8)
                if detail["threshold"] is not None:
                    # Equality on a continuous draw is meaningless; broadcast the median judgement.
                    truth = (np.full(paths, 1 if detail["satisfied"] else -1, dtype=np.int8) if condition.comparator == "eq"
                             else np.where(COMPARATORS[condition.comparator](values, detail["threshold"]), 1, -1).astype(np.int8))
                basis = "projected"
            else:
                projected = condition.metric in {"member_age", "date_reached"}
                detail = (calendar.evaluate(condition) if at else calendar.evaluate_actual(condition, None, "イベントの日付が指定されていません。")) \
                    if projected else self.current.evaluate(condition)
                satisfied = detail["satisfied"]
                truth = np.full(paths, 0 if satisfied is None else 1 if satisfied else -1, dtype=np.int8)
                basis = "projected" if projected else "current"
            truths.append(truth)
            details.append({**detail, "threshold_minor": condition.threshold_minor, "threshold_number": condition.threshold_number,
                            "threshold_date": condition.threshold_date, "basis": basis, "probability": _probability(truth)})
        # Ordered false/unknown/true values let min/max apply the three-valued all/any rules per path.
        combined = np.minimum.reduce(truths) if self.modes.get(event_id, "all") == "all" else np.maximum.reduce(truths)
        return combined, details
