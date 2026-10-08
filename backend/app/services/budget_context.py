"""Request-scoped loader for the data a budget computation reads repeatedly.

One budget summary resolves hundreds of plan lines, and nearly every
resolution step needs the same few collections: the month's transactions, the
client's accounts, its capsules, the registry lines for a period. Loading them
per line turns the summary into a query storm, so they were memoised in a
plain ``dict`` threaded through every call as an optional ``context``
argument. 26 functions carried that argument; only 5 ever read it, and each of
those carried a second code path for ``context is None``.

``BudgetContext`` replaces the dict. It holds the session and the client id
next to the caches, so a function that took
``(db, client_id, ..., context=None)`` now takes ``(ctx, ...)``: one argument
instead of three, always present, no second code path.

Every loader is lazy and memoised, so constructing a context costs nothing and
each collection is queried at most once however many plan lines ask for it.
The two ``*_lines`` memos take a builder callable because the lines are built
by the modules above this one -- that keeps the dependency pointing one way.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import cached_property

from sqlalchemy.orm import Session

from .. import models
from .capsule_service import capsule_balance as _capsule_balance
from .journal_legs import Leg, legs_in_period
from .periods import period_to_range


class BudgetContext:
    """The session, the client, and everything loaded once per computation."""

    def __init__(self, db: Session, client_id: int) -> None:
        self.db = db
        self.client_id = client_id
        self._period_transactions: dict[str, list[models.Transaction]] = {}
        self._period_legs: dict[str, list[Leg]] = {}
        self._capsule_balances: dict[int, float] = {}
        self._registry_lines: dict[str, list[dict]] = {}
        self._credit_settlement_lines: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # transactions

    def period_transactions(self, period: str) -> list[models.Transaction]:
        cached = self._period_transactions.get(period)
        if cached is None:
            start, end = period_to_range(period)
            cached = self.db.query(models.Transaction).filter(
                models.Transaction.client_id == self.client_id,
                models.Transaction.date >= start,
                models.Transaction.date < end,
            ).all()
            self._period_transactions[period] = cached
        return cached

    def period_legs(self, period: str) -> list[Leg]:
        """Every journal leg of the month, with its account resolved.

        Matching a plan line against the ledger is a per-leg question -- which
        account, which side -- so the leg list is cached the same way the
        transaction list is.
        """
        cached = self._period_legs.get(period)
        if cached is None:
            cached = legs_in_period(self.db, self.client_id, period)
            self._period_legs[period] = cached
        return cached

    # ------------------------------------------------------------------
    # accounts

    @cached_property
    def accounts(self) -> dict[int, models.Account]:
        return {
            account.id: account
            for account in self.db.query(models.Account)
            .filter(models.Account.client_id == self.client_id)
            .all()
        }

    def account(self, account_id: int | None) -> models.Account | None:
        if not account_id:
            return None
        return self.accounts.get(account_id)

    # ------------------------------------------------------------------
    # capsules

    @cached_property
    def capsules(self) -> list[models.Capsule]:
        return (
            self.db.query(models.Capsule)
            .filter(models.Capsule.client_id == self.client_id)
            .all()
        )

    @cached_property
    def capsule_by_id(self) -> dict[int, models.Capsule]:
        return {capsule.id: capsule for capsule in self.capsules}

    @cached_property
    def capsule_by_life_event_id(self) -> dict[int, models.Capsule]:
        return {
            capsule.life_event_id: capsule
            for capsule in self.capsules
            if capsule.life_event_id
        }

    @cached_property
    def capsule_account_ids(self) -> dict[int, int | None]:
        return {capsule.id: capsule.account_id for capsule in self.capsules}

    def capsule(self, capsule_id: int | None) -> models.Capsule | None:
        if not capsule_id:
            return None
        return self.capsule_by_id.get(capsule_id)

    def capsule_for_life_event(self, life_event_id: int | None) -> models.Capsule | None:
        if not life_event_id:
            return None
        return self.capsule_by_life_event_id.get(life_event_id)

    def capsule_balance(self, capsule: models.Capsule) -> float:
        balance = self._capsule_balances.get(capsule.id)
        if balance is None:
            balance = _capsule_balance(self.db, capsule)
            self._capsule_balances[capsule.id] = balance
        return balance

    # ------------------------------------------------------------------
    # display names

    @cached_property
    def target_name_maps(self) -> dict[str, dict[int, str]]:
        life_events = (
            self.db.query(models.LifeEvent)
            .filter(models.LifeEvent.client_id == self.client_id)
            .all()
        )
        products = (
            self.db.query(models.Product)
            .filter(models.Product.client_id == self.client_id)
            .all()
        )
        return {
            "account": {account.id: account.name for account in self.accounts.values()},
            "capsule": {capsule.id: capsule.name for capsule in self.capsules},
            "life_event": {item.id: item.name for item in life_events},
            "product": {item.id: item.name for item in products},
        }

    # ------------------------------------------------------------------
    # derived collections, built by the caller

    def registry_lines(self, period: str, build: Callable[[], list[dict]]) -> list[dict]:
        lines = self._registry_lines.get(period)
        if lines is None:
            lines = build()
            self._registry_lines[period] = lines
        return lines

    def credit_settlement_lines(self, period: str, build: Callable[[], list[dict]]) -> list[dict]:
        lines = self._credit_settlement_lines.get(period)
        if lines is None:
            lines = build()
            self._credit_settlement_lines[period] = lines
        return lines
