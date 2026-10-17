from app.services.ledger_valuation import calculate_account_valued_balance
from app.services.money_storage import to_minor, rule_amount_fields

from backend.app.domain.money import Money
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.services import capsule_service as capsule, ledger_service as ledger
    from backend.app.services.data_health_service import check_data_health
    from backend.app.services.fx_service import get_client_currency
    from backend.app.workflows import ledger_entry_workflow as workflow
except ModuleNotFoundError:
    from app import models, schemas
    from app.database import Base
    from app.services import capsule_service as capsule, ledger_service as ledger
    from app.services.data_health_service import check_data_health
    from app.services.fx_service import get_client_currency
    from app.workflows import ledger_entry_workflow as workflow

WHEN = date(2026, 10, 11)


@pytest.fixture
def posting():
    engine = create_engine("sqlite:///:memory:")

    # Withdrawing a reservation leans on the schema's own ON DELETE rules, and
    # SQLite applies them only when asked.
    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    client = models.Client(
        id=1,
        name="reservation-test",
        general_settings={},
    )
    accounts = [models.Account(
        client_id=1,
        name=name,
        account_type=kind,
    ) for name, kind in [("Cash", "asset"), ("Food", "expense"), ("Reserve", "asset"), ("Advance", "asset")]]
    db.add_all([client, *accounts])
    db.commit()
    try:
        yield db, client, *accounts
    finally:
        db.close()


def _rule(posting, *, auto_post=False, bound=True, percentage=False):
    db, _, cash, _, reserve, _ = posting
    owner = models.Capsule(
        client_id=1,
        name="Savings",
        target_amount_minor=to_minor(5000, "JPY"),
        monthly_contribution_minor=to_minor(0, "JPY"),
        funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=reserve.id, target_amount_minor=to_minor(5000, "JPY"))] if bound else [],
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
        **rule_amount_fields(10 if percentage else 3000, "percentage" if percentage else "fixed", "JPY"),
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


def test_auto_post_creates_balanced_transfer_and_records_its_cause(posting):
    """An auto-posted reservation records a proposal as well as the transfer.

    X3: the proposal is the only thing that says which entry caused the
    transfer. Without one, amending or deleting the trigger could not find what
    it had produced -- which is why this used to assert no proposal existed.
    """
    db, _, cash, _, reserve, _ = posting
    _rule(posting, auto_post=True)
    tx = _trigger(posting)
    transfer, = _apply(posting, tx)
    db.flush()
    assert db.query(models.Transaction).count() == 2
    entries = db.query(models.JournalEntry).filter_by(transaction_id=transfer.id).all()
    assert sorted((e.account_id, e.debit, e.credit) for e in entries) == sorted([
        (cash.id, 0, 3000), (reserve.id, 3000, 0),
    ])

    proposal = db.query(models.TransactionProposal).one()
    assert proposal.origin == "capsule"
    assert proposal.status == "posted"
    assert proposal.trigger_transaction_id == tx.id
    assert proposal.posted_transaction_id == transfer.id
    # The rule decided when it was configured; no person decided here.
    assert proposal.decided_by_client_id is None
    assert proposal.decided_at is not None


def test_unbound_capsule_does_not_block_trigger(posting):
    db = posting[0]
    _rule(posting, bound=False)
    tx = _trigger(posting)
    assert _apply(posting, tx) == []
    assert db.query(models.Transaction).one() is tx
    assert db.query(models.JournalEntry).count() == 2
    assert db.query(models.TransactionProposal).count() == 0


def test_target_clamps_to_own_pending_reservations(posting):
    db, _, cash, _, reserve, _ = posting
    _rule(posting)
    currency = get_client_currency(db, 1)
    for expected in [3000, 2000, 0]:
        ledger.create_transaction(
            db,
            client_id=1,
            date=WHEN,
            description="Existing savings",
            amount_minor=4000,
            currency=currency,
            from_account_id=cash.id,
            to_account_id=reserve.id,
        )
        result = _apply(posting, _trigger(posting))
        if expected:
            assert result[0].amount == expected
        else:
            assert result == []
    assert db.query(models.TransactionProposal).count() == 2


def test_percentage_uses_whole_compound_amount(posting):
    _rule(posting, percentage=True)
    proposal, = _apply(posting, _trigger(posting, compound=True))
    assert proposal.amount == 1000


@pytest.mark.parametrize("auto_post", [False, True])
@pytest.mark.parametrize("currency,expected", [("JPY", 13.0), ("USD", 12.63), ("EUR", 12.63)])
def test_percentage_reservation_rounds_minor_units_and_balances_legs(posting, auto_post, currency, expected):
    db, _, cash, expense, _, _ = posting
    _, rule = _rule(posting, percentage=True, auto_post=auto_post)
    rule.percentage_bp = 1250
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
    before = [calculate_account_valued_balance(db, a) for a in [cash, reserve]]
    transfer = ledger.approve_proposal(db, proposal, actor_client_id=1)
    db.flush()
    assert calculate_account_valued_balance(db, cash) == before[0] - 3000
    assert calculate_account_valued_balance(db, reserve) == before[1] + 3000
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


# X3: amending or deleting a trigger re-evaluates what its rules produced.
# These drive the workflow rather than the service, because the re-evaluation
# is the workflow's composition: withdraw, rebuild, apply, close once.


def _amend(posting, transaction_id, **changes):
    db = posting[0]
    return workflow.amend_entry(
        db, 1, transaction_id, schemas.TransactionUpdate(**changes), commit=False,
    )


def test_deleting_a_trigger_withdraws_its_queued_reservation(posting):
    db, _, _, _, _, _ = posting
    _rule(posting)
    tx = _trigger(posting)
    capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.flush()
    assert db.query(models.TransactionProposal).count() == 1

    assert workflow.remove_entry(db, 1, tx.id, commit=False) is True
    db.flush()
    assert db.query(models.TransactionProposal).count() == 0
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0


def test_deleting_a_trigger_takes_the_posted_transfer_with_it(posting):
    db, _, cash, _, reserve, _ = posting
    _rule(posting, auto_post=True)
    tx = _trigger(posting)
    transfer, = capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.flush()
    assert calculate_account_valued_balance(db, reserve) == 3000

    assert workflow.remove_entry(db, 1, tx.id, commit=False) is True
    db.flush()
    # The money goes back where it came from: the reservation had no basis
    # once the entry that caused it was gone.
    assert db.get(models.Transaction, transfer.id) is None
    assert db.query(models.TransactionProposal).count() == 0
    assert db.query(models.JournalEntry).count() == 0
    assert calculate_account_valued_balance(db, reserve) == 0
    assert calculate_account_valued_balance(db, cash) == 0


def test_a_rejected_reservation_survives_its_trigger(posting):
    db, _, _, _, _, _ = posting
    _rule(posting)
    tx = _trigger(posting)
    proposal, = capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    ledger.reject_proposal(db, proposal, actor_client_id=1, note="not this month")
    db.flush()

    assert workflow.remove_entry(db, 1, tx.id, commit=False) is True
    db.flush()
    # The database clears the trigger, not the ORM, so the cached row has to be
    # expired before it tells the truth.
    db.expire_all()
    # A person decided this, about something that has already happened. The
    # foreign key clears the trigger; the record of the decision stays.
    survivor = db.query(models.TransactionProposal).one()
    assert survivor.id == proposal.id
    assert survivor.status == "rejected"
    assert survivor.note == "not this month"
    assert survivor.trigger_transaction_id is None


def test_amending_the_amount_re_evaluates_the_reservation(posting):
    db, _, cash, _, reserve, _ = posting
    _rule(posting, percentage=True)
    tx = _trigger(posting)
    capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.flush()
    assert db.query(models.TransactionProposal).one().amount == 1000

    assert _amend(posting, tx.id, amount=4000) is not None
    db.flush()
    # One reservation, at the new figure. It used to be left at the old one.
    reserved = db.query(models.TransactionProposal).one()
    assert reserved.amount == 400
    assert reserved.trigger_transaction_id == tx.id
    assert db.get(models.Transaction, tx.id).amount == 4000


def test_amending_a_posted_reservation_replaces_the_transfer(posting):
    db, _, _, _, reserve, _ = posting
    _rule(posting, auto_post=True, percentage=True)
    tx = _trigger(posting)
    first, = capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.flush()
    assert calculate_account_valued_balance(db, reserve) == 1000

    before = db.query(models.TransactionProposal).one().idempotency_key
    assert _amend(posting, tx.id, amount=4000) is not None
    db.flush()
    posted = db.query(models.TransactionProposal).one()
    assert posted.status == "posted"
    assert posted.amount == 400
    # A different reservation, not the old one edited: the key is derived from
    # the amount and legs. SQLite hands the replacement the deleted row's id,
    # so the key is what tells them apart.
    assert posted.idempotency_key != before
    # 400, not 1400: the first transfer went back out of the capsule's account.
    assert calculate_account_valued_balance(db, reserve) == 400
    assert db.query(models.Transaction).count() == 2
    assert db.query(models.JournalEntry).count() == 4


def test_amending_a_description_keeps_one_reservation(posting):
    """The idempotency key ignores the description, so the rebuild must flush."""
    db, _, _, _, _, _ = posting
    _rule(posting)
    tx = _trigger(posting)
    capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.flush()
    before = db.query(models.TransactionProposal).one().idempotency_key

    assert _amend(posting, tx.id, description="Lunch with a colleague") is not None
    db.flush()
    after = db.query(models.TransactionProposal).one()
    assert after.idempotency_key == before
    assert after.amount == 3000


def test_amending_so_no_rule_fires_leaves_no_reservation(posting):
    db, _, _, _, reserve, _ = posting
    _rule(posting, auto_post=True)
    tx = _trigger(posting)
    capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.flush()
    assert calculate_account_valued_balance(db, reserve) == 3000

    # The rule reserves a flat 3000 but never more than the capsule's target
    # less its balance, and it cannot reserve more than it is told to move.
    db.query(models.CapsuleRule).one().is_active = False
    assert _amend(posting, tx.id, amount=9000) is not None
    db.flush()
    assert db.query(models.TransactionProposal).count() == 0
    assert calculate_account_valued_balance(db, reserve) == 0


def test_amending_an_unknown_entry_withdraws_nothing(posting):
    db, _, _, _, _, _ = posting
    _rule(posting)
    tx = _trigger(posting)
    capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.commit()

    assert _amend(posting, tx.id + 999, amount=1) is None
    assert db.query(models.TransactionProposal).one().amount == 3000
    assert db.get(models.Transaction, tx.id) is not None


def test_the_reservation_read_reports_both_kinds_and_writes_nothing(posting):
    db, _, _, _, _, _ = posting
    owner, _ = _rule(posting)
    tx = _trigger(posting)
    proposal, = capsule.apply_capsule_rules_for_transaction(db, tx, commit=False)
    db.commit()

    listed, = workflow.entry_capsule_reservations(db, 1, tx.id)
    assert listed.proposal_id == proposal.id
    assert (listed.capsule_id, listed.capsule_name) == (owner.id, "Savings")
    assert (listed.amount, listed.currency, listed.status) == (3000, "JPY", "pending")
    assert listed.posted_transaction_id is None
    assert workflow.entry_capsule_reservations(db, 1, tx.id + 999) == []
    assert not db.new and not db.dirty and not db.deleted
