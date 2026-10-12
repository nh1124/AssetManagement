from backend.app.domain.money import Money
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.services import capsule_service as capsule, ledger_service as ledger
    from backend.app.services.data_health_service import check_data_health
    from backend.app.routers.capsules import preview_for_transaction
except ModuleNotFoundError:
    from app import models, schemas
    from app.database import Base
    from app.services import capsule_service as capsule, ledger_service as ledger
    from app.services.data_health_service import check_data_health
    from app.routers.capsules import preview_for_transaction

WHEN = date(2026, 10, 11)


@pytest.fixture
def posting():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    client = models.Client(
        id=1,
        name="reservation-test",
        general_settings={},
        ai_config={},
    )
    accounts = [models.Account(
        client_id=1,
        name=name,
        account_type=kind,
        balance=0,
    ) for name, kind in [("Cash", "asset"), ("Food", "expense"), ("Reserve", "asset"), ("Advance", "asset")]]
    db.add_all([client, *accounts])
    db.commit()
    try:
        yield db, client, *accounts
        assert db.query(models.CapsuleHolding).count() == 0
    finally:
        db.close()


def _rule(posting, *, auto_post=False, bound=True, percentage=False):
    db, _, cash, _, reserve, _ = posting
    owner = models.Capsule(
        client_id=1,
        name="Savings",
        target_amount=5000,
        monthly_contribution=0,
        account_id=reserve.id if bound else None,
        auto_post=auto_post,
    )
    db.add(owner)
    db.flush()
    rule = models.CapsuleRule(
        client_id=1,
        capsule_id=owner.id,
        trigger_type="Expense",
        source_mode="fixed_account",
        source_account_id=cash.id,
        amount_type="percentage" if percentage else "fixed",
        amount_value=10 if percentage else 3000,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    return owner, rule


def _trigger(posting, *, compound=False):
    db, _, cash, expense, _, advance = posting
    return ledger.create_transaction(
        db,
        client_id=1,
        date=WHEN,
        description="Lunch",
        amount_minor=Money.from_major(str(10000), "JPY").minor,
        currency="JPY",
        legs=[
            ledger.Leg(
                account_id=cash.id,
                credit=10000,
            ),
            ledger.Leg(
                account_id=expense.id,
                debit=6000 if compound else 10000,
            ),
        ] + ([ledger.Leg(
            account_id=advance.id,
            debit=4000,
        )] if compound else []),
    )


def _apply(posting, tx):
    return capsule.apply_capsule_rules_for_transaction(posting[0], tx, commit=False)


def test_reservation_queues_proposal(posting):
    db, _, cash, _, reserve, _ = posting
    owner, rule = _rule(posting)
    tx = _trigger(posting)
    proposal, = _apply(posting, tx)
    assert db.query(models.TransactionProposal).one() is proposal
    assert db.query(models.Transaction).one() is tx
    assert db.query(models.JournalEntry).count() == 2
    assert proposal.origin == "capsule"
    assert proposal.origin_ref == {"capsule_id": owner.id, "rule_id": rule.id}
    assert proposal.trigger_transaction_id == tx.id
    assert proposal.date == WHEN
    assert proposal.description == "Capsule reservation: Savings"
    assert sorted((leg["account_id"], leg["debit"], leg["credit"]) for leg in proposal.legs) == sorted([
        (cash.id, 0, 3000), (reserve.id, 3000, 0),
    ])


def test_auto_post_creates_balanced_transfer(posting):
    db, _, cash, _, reserve, _ = posting
    _rule(posting, auto_post=True)
    transfer, = _apply(posting, _trigger(posting))
    db.flush()
    assert db.query(models.Transaction).count() == 2
    assert db.query(models.TransactionProposal).count() == 0
    entries = db.query(models.JournalEntry).filter_by(transaction_id=transfer.id).all()
    assert sorted((e.account_id, e.debit, e.credit) for e in entries) == sorted([
        (cash.id, 0, 3000), (reserve.id, 3000, 0),
    ])


def test_unbound_capsule_does_not_block_trigger(posting):
    db = posting[0]
    _rule(posting, bound=False)
    tx = _trigger(posting)
    assert _apply(posting, tx) == []
    assert db.query(models.Transaction).one() is tx
    assert db.query(models.JournalEntry).count() == 2
    assert db.query(models.TransactionProposal).count() == 0


def test_target_clamps_to_journal_balance(posting):
    db, _, cash, _, reserve, _ = posting
    _rule(posting)
    for amount in [4000, 1000]:
        ledger.create_transaction(
            db,
            client_id=1,
            date=WHEN,
            description="Existing savings",
            amount_minor=Money.from_major(str(amount), "JPY").minor,
            from_account_id=cash.id,
            to_account_id=reserve.id,
        )
        result = _apply(posting, _trigger(posting))
        if amount == 4000:
            assert result[0].amount == 1000
        else:
            assert result == []
    assert db.query(models.TransactionProposal).count() == 1


def test_percentage_uses_whole_compound_amount(posting):
    _rule(posting, percentage=True)
    proposal, = _apply(posting, _trigger(posting, compound=True))
    assert proposal.amount == 1000


@pytest.mark.parametrize("auto_post", [False, True])
@pytest.mark.parametrize("currency,expected", [("JPY", 13.0), ("USD", 12.63), ("EUR", 12.63)])
def test_percentage_reservation_rounds_minor_units_and_balances_legs(posting, auto_post, currency, expected):
    db, _, cash, expense, _, _ = posting
    _, rule = _rule(posting, percentage=True, auto_post=auto_post)
    rule.amount_value = 12.5
    db.flush()
    tx = ledger.create_transaction(
        db, client_id=1, date=WHEN, description="Uneven percentage",
        amount_minor=Money.from_major(str(101.0), currency).minor, currency=currency,
        from_account_id=cash.id, to_account_id=expense.id,
    )
    reservation, = _apply(posting, tx)
    assert repr(reservation.amount) == repr(expected)
    assert reservation.currency == currency
    if auto_post:
        db.flush()
        entries = db.query(models.JournalEntry).filter_by(transaction_id=reservation.id).all()
        debits = sum(entry.debit_minor for entry in entries)
        credits = sum(entry.credit_minor for entry in entries)
    else:
        debits = sum(leg["debit"] for leg in reservation.legs)
        credits = sum(leg["credit"] for leg in reservation.legs)
    assert debits == credits == reservation.amount_minor


def test_approval_moves_account_balances(posting):
    db, _, cash, _, reserve, _ = posting
    _rule(posting)
    proposal, = _apply(posting, _trigger(posting))
    before = [ledger.calculate_account_journal_balance(db, a) for a in [cash, reserve]]
    transfer = ledger.approve_proposal(db, proposal, actor_client_id=1)
    db.flush()
    assert ledger.calculate_account_journal_balance(db, cash) == before[0] - 3000
    assert ledger.calculate_account_journal_balance(db, reserve) == before[1] + 3000
    assert db.query(models.Transaction).count() == 2
    assert db.query(models.JournalEntry).filter_by(transaction_id=transfer.id).count() == 2


def test_repeated_trigger_queues_only_once(posting):
    db = posting[0]
    _rule(posting)
    tx = _trigger(posting)
    first, = _apply(posting, tx)
    second, = _apply(posting, tx)
    assert second.id == first.id
    assert db.query(models.TransactionProposal).count() == 1


def test_detached_preview_writes_nothing(posting):
    db, client, cash, expense, reserve, _ = posting
    _rule(posting)
    entries = [schemas.TransactionLeg(
        account_id=cash.id,
        credit=10000,
    ), schemas.TransactionLeg(
        account_id=expense.id,
        debit=10000,
    )]
    specs = capsule.capsule_transfer_specs(
        db,
        client.id,
        entries=entries,
        description="Lunch",
        amount=10000,
    )
    assert len(specs) == 1
    assert specs[0].source_account_id == cash.id
    assert specs[0].destination_account_id == reserve.id
    assert specs[0].amount == 3000
    assert specs[0].auto_post is False
    response = preview_for_transaction(
        schemas.CapsuleTransactionPreviewRequest(
            description="Lunch",
            amount=10000,
            date=WHEN,
            legs=entries,
        ),
        db=db,
        current_client=client,
    )
    assert response[0]["capsule_name"] == "Savings"
    assert not db.new and not db.dirty
    assert db.query(models.TransactionProposal).count() == 0
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0


def test_health_reports_only_unbound_active_capsule(posting):
    db = posting[0]
    unbound, _ = _rule(posting, bound=False)
    bound, _ = _rule(posting)
    issue = next(i for i in check_data_health(db, 1)["issues"] if i["code"] == "capsule_without_account")
    assert issue["severity"] == "warning"
    assert issue["repairable"] is False
    assert issue["count"] == 1
    assert issue["items"] == [{"capsule_id": unbound.id, "name": unbound.name, "rule_count": 1}]
    assert bound.id not in [i["capsule_id"] for i in issue["items"]]
