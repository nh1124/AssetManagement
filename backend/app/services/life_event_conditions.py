"""Report a plan's assumptions; evaluation never changes its events or projection."""
from datetime import date
from operator import eq, ge, le

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import NotFound
from ..domain.money import Money
from .analysis_service import calculate_logical_balance, LIQUID_ACCOUNT_NAMES
from .institution_service import locked_accounts
from .reporting_service import get_balance_sheet
from .capsule_service import claimed_minor
from .fx_service import get_client_currency
from .ledger_valuation import calculate_account_balances
from .strategy_service import get_life_events_with_progress

REFERENCE_MODELS = {
    "account_balance": models.Account,
    "capsule_claim": models.Capsule,
    "goal_progress": models.LifeEvent,
    "member_age": models.HouseholdMember,
}
COMPARATORS = {"gte": ge, "lte": le, "eq": eq}
MONEY_METRICS = {"net_worth", "free_cash", "account_balance", "capsule_claim"}


def _event(db: Session, client_id: int, event_id: int) -> models.LifeEvent:
    value = db.query(models.LifeEvent).filter_by(client_id=client_id, id=event_id).first()
    if value is None:
        raise NotFound("ゴールが見つかりません。")
    return value


def create_condition(db: Session, client_id: int, event_id: int, payload: schemas.LifeEventConditionCreate) -> models.LifeEventCondition:
    _event(db, client_id, event_id)
    model = REFERENCE_MODELS.get(payload.metric)
    if model is not None and db.query(model).filter_by(client_id=client_id, id=payload.reference_id).first() is None:
        raise NotFound("同じクライアントの対象を選択してください。")
    row = models.LifeEventCondition(client_id=client_id, life_event_id=event_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_condition(db: Session, client_id: int, event_id: int, condition_id: int) -> None:
    _event(db, client_id, event_id)
    row = db.query(models.LifeEventCondition).filter_by(client_id=client_id, life_event_id=event_id, id=condition_id).first()
    if row is None:
        raise NotFound("条件が見つかりません。")
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
            metric: {row.id: row for row in db.query(model).filter(model.client_id == client_id).all()}
            for metric, model in REFERENCE_MODELS.items()
            if metric in {row.metric for row in conditions}
        }
        self.figures: dict[tuple[str, int | None], tuple[float | int | date | None, str | None]] = {}
        self.accounts = db.query(models.Account).filter_by(client_id=client_id).all() if {row.metric for row in conditions} & {"net_worth", "free_cash", "account_balance"} else []
        self.balances = calculate_account_balances(db, self.accounts)
        self.claims: dict[int, dict[str, int]] = {}
        self.actual_minor: dict[tuple[str, int | None], int] = {}
        self.progress: dict[int, dict] | None = None

    def foreign(self, figures: dict[str, int]) -> str | None:
        currencies = sorted(code for code, minor in figures.items() if code != self.currency and minor != 0)
        return f"通貨が異なります（{'・'.join(currencies)}／{self.currency}）。" if currencies else None

    def claim(self, capsule_id: int) -> dict[str, int]:
        if capsule_id not in self.claims:
            self.claims[capsule_id] = claimed_minor(self.db, self.client_id, capsule_id)
        return self.claims[capsule_id]

    def aggregate_currency_reason(self, metric: str) -> str | None:
        for account in self.accounts:
            relevant = (account.is_active and account.account_type in {"asset", "item", "liability"}) if metric == "net_worth" else (account.name in LIQUID_ACCOUNT_NAMES or account.account_type == "liability")
            if relevant:
                reason = self.foreign(self.balances[account.id].balances_minor)
                if reason:
                    return reason
        if metric == "free_cash":
            # Access deductions also include assets outside the legacy cash names.
            # A foreign locked holding must not sneak into a scalar money condition.
            for locked in locked_accounts(self.db, self.client_id):
                reason = self.foreign(locked["balances_minor"])
                if reason:
                    return reason
            for capsule in self.db.query(models.Capsule).filter_by(client_id=self.client_id).all():
                reason = self.foreign(self.claim(capsule.id))
                if reason:
                    return reason
            # The logical reader also values this month's posted budget spending.
            foreign_spending = self.db.query(models.Transaction.id).join(models.JournalEntry).join(models.Account).filter(
                models.Transaction.client_id == self.client_id,
                models.Transaction.date >= date.today().replace(day=1),
                models.Transaction.date <= date.today(),
                models.Transaction.currency != self.currency,
                models.Account.account_type == "expense",
            ).first()
            if foreign_spending:
                return "当月の支出に異なる通貨が含まれます。"
        return None

    def actual(self, row: models.LifeEventCondition) -> tuple[float | int | date | None, str | None]:
        key = row.metric, row.reference_id
        if key in self.figures:
            return self.figures[key]
        reference = self.references.get(row.metric, {}).get(row.reference_id)
        if row.metric in REFERENCE_MODELS and reference is None:
            return None, "対象が削除されたか、見つかりません。"
        actual, reason = None, None
        if row.metric in {"net_worth", "free_cash"}:
            reason = self.aggregate_currency_reason(row.metric)
            if reason is None:
                actual = get_balance_sheet(self.db, client_id=self.client_id)["net_worth"] if row.metric == "net_worth" else calculate_logical_balance(self.db, self.client_id)
        elif row.metric == "account_balance":
            figures = self.balances[reference.id].balances_minor
            reason = self.foreign(figures)
            if reason is None:
                self.actual_minor[key] = figures.get(self.currency, 0)
                actual = Money(self.actual_minor[key], self.currency).to_float()
        elif row.metric == "capsule_claim":
            figures = self.claim(reference.id)
            reason = self.foreign(figures)
            if reason is None:
                self.actual_minor[key] = figures.get(self.currency, 0)
                actual = Money(self.actual_minor[key], self.currency).to_float()
        elif row.metric == "goal_progress":
            if reference.direction == "income":
                return None, "収入イベントには積立進捗がありません。"
            for capsule in self.db.query(models.Capsule).filter_by(client_id=self.client_id, life_event_id=reference.id).all():
                reason = self.foreign(self.claim(capsule.id))
                if reason:
                    break
            if reason is None:
                if self.progress is None:
                    self.progress = {event["id"]: event for event in get_life_events_with_progress(self.db, self.client_id, include_archived=True)}
                actual = self.progress[reference.id]["progress_percentage"]
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
        return _evaluate(db, client_id, db.query(models.LifeEvent).filter_by(client_id=client_id).order_by(models.LifeEvent.id).all(), as_of)
