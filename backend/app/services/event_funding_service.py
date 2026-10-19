"""資金の割り当て: which asset accounts pay a life event, or receive it, and by what share.

The simulation settings of a scenario say, per event, e.g. 証券口座 60% and 貯蓄口座 40%.
Shares are of the whole event and add up to at most 100%; the rest is the residual
net worth's. The simulation moves each share through its account, and making the plan
from the goal earmarks an expense's share in each of its accounts.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import NotFound, Refused
from .cache_service import invalidate_client

FULL = 10000


def shares(db: Session, event_ids) -> dict[int, list[tuple[int, int]]]:
    """{event_id: [(account_id, share_bp), ...]} in the order the shares were set."""
    ids = list(event_ids)
    if not ids:
        return {}
    found: dict[int, list[tuple[int, int]]] = {}
    for row in db.query(models.LifeEventFunding).filter(models.LifeEventFunding.life_event_id.in_(ids)).order_by(models.LifeEventFunding.id):
        found.setdefault(row.life_event_id, []).append((row.account_id, row.share_bp))
    return found


def parts(total_minor: int, funding: list[tuple[int, int]]) -> dict[int, int]:
    """{account_id: minor} of an amount split by the shares; rounding goes to the largest share."""
    split = {account_id: total_minor * share // FULL for account_id, share in funding}
    if funding and sum(share for _, share in funding) == FULL:
        largest = max(funding, key=lambda item: item[1])[0]
        split[largest] += total_minor - sum(split.values())
    return split


def set_fundings(db: Session, client_id: int, event_id: int, items: list[schemas.LifeEventFundingInput]) -> models.LifeEvent:
    """Replace an event's 資金の割り当て with the given accounts and shares."""
    event = db.query(models.LifeEvent).filter_by(id=event_id, client_id=client_id).first()
    if event is None:
        raise NotFound("ライフイベントが見つかりません。")
    account_ids = [item.account_id for item in items]
    if len(set(account_ids)) != len(account_ids):
        raise Refused("同じ口座は一度だけ選んでください。", status_code=422)
    assets = {account.id for account in db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset", models.Account.id.in_(account_ids))}
    if assets != set(account_ids):
        raise NotFound("同じクライアントの資産口座を選んでください。")
    basis_points = [round(item.share * 100) for item in items]
    if any(share <= 0 for share in basis_points) or sum(basis_points) > FULL:
        raise Refused("割合は口座ごとに 0% より大きく、合計 100% 以下にしてください。", status_code=422)
    try:
        event.fundings.clear()
        db.flush()
        for account_id, share in zip(account_ids, basis_points):
            event.fundings.append(models.LifeEventFunding(account_id=account_id, share_bp=share))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    invalidate_client(client_id)
    return event


def copy_fundings(db: Session, event_map: dict[int, int]) -> None:
    """A copied scenario's events keep their accounts and shares."""
    for source_id, funding in shares(db, event_map).items():
        for account_id, share in funding:
            db.add(models.LifeEventFunding(life_event_id=event_map[source_id], account_id=account_id, share_bp=share))
    db.flush()
