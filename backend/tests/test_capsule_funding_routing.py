"""F1b: shared destinations, exact plan routing, and capsule-owned claims."""
from datetime import date
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app import models, schemas
from app.database import Base
from app.domain.errors import Invalid, NotFound
from app.models.money import BasisPoints
from app.routers.capsules import _rule_to_dict
from app.services import capsule_service as capsule, ledger_service as ledger
from app.services.ledger_valuation import calculate_account_valued_balance
from app.workflows.ledger_entry_workflow import record_entry, amend_entry

WHEN = date(2026, 10, 12)


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add_all([
            models.Client(id=1, name="Owner", general_settings={"currency": "JPY"}),
            models.Client(id=2, name="Other", general_settings={"currency": "JPY"}),
        ])
        session.flush()
        session.add_all([
            models.Account(id=1, client_id=1, name="Cash", account_type="asset"),
            models.Account(id=2, client_id=1, name="NISA", account_type="asset"),
            models.Account(id=3, client_id=1, name="Salary", account_type="income"),
            models.Account(id=4, client_id=1, name="Second", account_type="asset"),
            models.Account(id=5, client_id=1, name="Third", account_type="asset"),
            models.Account(id=6, client_id=2, name="Foreign", account_type="asset"),
        ])
        session.commit()
        yield session
    engine.dispose()


def _owner(db, name="PC", *, target=100000, legacy=2, auto_post=False):
    return capsule.create_capsule(db, 1, schemas.CapsuleCreate(
        name=name, target_amount=target, monthly_contribution=0,
        account_id=legacy, auto_post=auto_post,
    ))


def _jpy_claim(db, client_id, capsule_id, account_id=None) -> int:
    """The yen part of a capsule's claim.

    claimed_minor answers per currency and never totals, because a reservation
    triggered by a dollar payment is counted in cents and adding those to yen
    is the operation B5 removed from the account balance. Every fixture here is
    in yen, so these tests ask for that one entry; the per-currency shape has
    its own test below.
    """
    return capsule.claimed_minor(db, client_id, capsule_id, account_id).get("JPY", 0)


def _plan(db, owner, *lines):
    return capsule.set_funding_sources(db, 1, owner.id, [
        schemas.CapsuleFundingSourceInput(
            account_id=account_id, target_amount=target, max_share_bp=share,
        ) for account_id, target, share in lines
    ])


def _rule(db, owner, amount=10000, destination=None, **changes):
    return capsule.create_rule(db, 1, schemas.CapsuleRuleCreate(**{
        "capsule_id": owner.id, "trigger_type": "Income",
        "source_mode": "fixed_account", "source_account_id": 1,
        "amount_type": "fixed", "amount_value": amount,
        "destination_account_id": destination, **changes,
    }))


def _salary(db):
    return record_entry(db, 1, schemas.TransactionCreate(
        date=WHEN, description="Salary", amount=200000, currency="JPY",
        legs=[schemas.TransactionLeg(account_id=1, debit=200000),
              schemas.TransactionLeg(account_id=3, credit=200000)],
    ))


def _preview(db):
    return capsule.capsule_transfer_specs(
        db, 1, entries=[schemas.TransactionLeg(account_id=1, debit=200000),
                       schemas.TransactionLeg(account_id=3, credit=200000)],
        description="Salary", amount=200000, currency="JPY",
    )


def _saved_plan(owner):
    return [(s.id, s.account_id, s.target_amount_minor, s.max_share_bp, s.sort_order)
            for s in owner.funding_sources]


@pytest.mark.parametrize("auto_post", [False, True])
def test_one_nisa_two_capsules_each_reserves_and_claims_its_own_amount(db, auto_post):
    # Unattributed pre-existing balance was the F0-pinned clamp bug's trigger.
    ledger.create_transaction(db, client_id=1, date=WHEN, description="Existing NISA assets",
                              amount_minor=500000, currency="JPY", from_account_id=1, to_account_id=2)
    db.commit()
    pc = _owner(db, "PC", target=5000, auto_post=auto_post)
    retirement = _owner(db, "Retirement", target=10000, auto_post=auto_post)
    _plan(db, pc, (2, 5000, 3000))
    _plan(db, retirement, (2, 10000, 6000))
    pc_rule = _rule(db, pc, 5000, 2)
    retirement_rule = _rule(db, retirement, 10000, 2)
    salary = _salary(db)
    proposals = db.query(models.TransactionProposal).order_by(models.TransactionProposal.id).all()
    assert len(proposals) == 2
    assert [(p.amount_minor, p.origin_ref) for p in proposals] == [
        (5000, {"capsule_id": pc.id, "rule_id": pc_rule.id}),
        (10000, {"capsule_id": retirement.id, "rule_id": retirement_rule.id}),
    ]
    assert all(p.origin == "capsule" and p.trigger_transaction_id == salary.id for p in proposals)
    for p in proposals:
        assert [(leg["account_id"], leg["debit"]) for leg in p.legs if leg["debit"]] == [(2, p.amount_minor)]
    if not auto_post:
        assert _jpy_claim(db, 1, pc.id) == _jpy_claim(db, 1, retirement.id) == 0
        assert _preview(db) == []  # The pending amounts fill both targets.
        for p in proposals:
            ledger.approve_proposal(db, p, actor_client_id=1)
        db.commit()
    for p in proposals:
        legs = db.query(models.JournalEntry).filter_by(transaction_id=p.posted_transaction_id).all()
        assert [(leg.account_id, leg.capsule_id) for leg in legs if leg.debit_minor] == [(2, p.origin_ref["capsule_id"])]
        assert all(leg.capsule_id is None for leg in legs if leg.credit_minor)
    assert _jpy_claim(db, 1, pc.id, 2) == _jpy_claim(db, 1, pc.id) == 5000
    assert _jpy_claim(db, 1, retirement.id, 2) == _jpy_claim(db, 1, retirement.id) == 10000
    assert calculate_account_valued_balance(db, db.get(models.Account, 2)) == 515000
    assert _preview(db) == []
    # Repeated application returns the same two reservations even at target.
    assert len(capsule.apply_capsule_rules_for_transaction(db, salary, commit=False)) == 2
    assert db.query(models.TransactionProposal).count() == 2


def test_unspecified_destination_splits_exactly_by_plan_and_zero_gets_nothing(db):
    owner = _owner(db, legacy=None)
    _plan(db, owner, (2, 1, None), (4, 1, None), (5, 1, None), (3, 0, None))
    _rule(db, owner)
    specs = _preview(db)
    assert [(s.destination_account_id, s.amount_minor) for s in specs] == [(2, 3334), (4, 3333), (5, 3333)]
    assert sum(s.amount_minor for s in specs) == 10000
    salary = _salary(db)
    proposals = db.query(models.TransactionProposal).all()
    assert len(proposals) == 3
    assert sum(p.amount_minor for p in proposals) == 10000
    assert all(p.origin_ref["capsule_id"] == owner.id and p.trigger_transaction_id == salary.id for p in proposals)
    for proposal in proposals:
        ledger.approve_proposal(db, proposal, actor_client_id=1)
    db.commit()
    assert _jpy_claim(db, 1, owner.id) == 10000
    assert [_jpy_claim(db, 1, owner.id, a) for a in [2, 4, 5]] == [3334, 3333, 3333]


def test_explicit_destination_gets_whole_amount_regardless_of_weight(db):
    owner = _owner(db)
    _plan(db, owner, (2, 0, None), (4, 100000, None))
    _rule(db, owner, destination=2)
    spec, = _preview(db)
    assert (spec.destination_account_id, spec.amount_minor) == (2, 10000)


def test_no_plan_uses_legacy_destination(db):
    owner = _owner(db)
    _rule(db, owner)
    _salary(db)
    proposal = db.query(models.TransactionProposal).one()
    assert any(leg["account_id"] == 2 and leg["debit"] == 10000 for leg in proposal.legs)


@pytest.mark.parametrize("explicit", [False, True])
def test_same_source_destination_does_not_reserve(db, explicit):
    owner = _owner(db)
    _plan(db, owner, (1, 10, None), (2, 10, None))
    _rule(db, owner, destination=1 if explicit else None)
    specs = _preview(db)
    assert [(s.destination_account_id, s.amount_minor) for s in specs] == ([] if explicit else [(2, 5000)])


def test_all_zero_plan_proposes_nothing(db):
    owner = _owner(db)
    _plan(db, owner, (2, 0, None), (4, 0, None))
    _rule(db, owner)
    assert _preview(db) == []


@pytest.mark.parametrize("destination", [4, 6, 99999])
def test_destination_outside_plan_refused_before_create_or_update_writes(db, destination):
    owner = _owner(db)
    _plan(db, owner, (2, 100000, None))
    message = f"Destination account {destination} is not in capsule {owner.id}'s funding plan"
    with pytest.raises(NotFound) as error:
        _rule(db, owner, destination=destination)
    assert str(error.value) == message
    assert db.query(models.CapsuleRule).count() == 0
    assert not db.new and not db.dirty and not db.deleted
    rule = _rule(db, owner, destination=2)
    with pytest.raises(NotFound) as error:
        capsule.update_rule(db, 1, rule.id, schemas.CapsuleRuleUpdate(
            destination_account_id=destination, amount_value=1, is_active=False,
        ))
    assert str(error.value) == message
    assert not db.new and not db.dirty and not db.deleted
    db.commit()
    db.refresh(rule)
    assert (rule.destination_account_id, rule.amount_minor, rule.is_active) == (2, 10000, True)


def test_changing_capsule_checks_retained_destination_against_new_plan(db):
    first = _owner(db)
    second = _owner(db, "Retirement")
    _plan(db, first, (2, 100000, None))
    _plan(db, second, (4, 100000, None))
    rule = _rule(db, first, destination=2)
    with pytest.raises(NotFound):
        capsule.update_rule(db, 1, rule.id, schemas.CapsuleRuleUpdate(capsule_id=second.id))
    assert rule.capsule_id == first.id
    assert not db.new and not db.dirty and not db.deleted
    capsule.update_rule(db, 1, rule.id, schemas.CapsuleRuleUpdate(capsule_id=second.id, destination_account_id=4))
    assert (rule.capsule_id, rule.destination_account_id) == (second.id, 4)


def test_removing_named_destination_is_refused_and_names_rule(db):
    owner = _owner(db)
    _plan(db, owner, (2, 100000, None), (4, 50000, None))
    rule = _rule(db, owner, destination=2, is_active=False)
    before = _saved_plan(owner)
    for replacement in [[], [(4, 1, None)]]:
        with pytest.raises(Invalid) as error:
            _plan(db, owner, *replacement)
        assert str(error.value) == f"Cannot remove account 2: rule {rule.id} names it as its destination"
        assert _saved_plan(owner) == before
        assert not db.new and not db.dirty and not db.deleted
    assert _rule_to_dict(rule)["destination_account_id"] == 2
    assert schemas.CapsuleRule.model_validate(rule).destination_account_id == 2
    capsule.update_rule(db, 1, rule.id, schemas.CapsuleRuleUpdate(destination_account_id=None))
    assert _plan(db, owner, (4, 1, None))[0].account_id == 4


def test_share_invariant_is_atomic_and_counts_null_as_zero(db):
    pc = _owner(db)
    retirement = _owner(db, "Retirement")
    third = _owner(db, "Travel")
    _plan(db, pc, (2, 5000, 6000))
    _plan(db, retirement, (2, 10000, None), (4, 10, 10000))
    _plan(db, third, (2, 100, None))
    before = _saved_plan(retirement)
    with pytest.raises(Invalid) as error:
        _plan(db, retirement, (2, 123, 5000), (4, 456, 0))
    # The person typed a percentage, so the refusal answers in one.
    assert str(error.value) == (
        "Declared capsule shares for account 2 (NISA) total 110%, "
        "which is more than the account has"
    )
    assert not db.new and not db.dirty and not db.deleted
    db.commit()
    db.expire_all()
    assert _saved_plan(retirement) == before
    _plan(db, retirement, (2, 10000, 4000), (4, 10, 10000))
    assert capsule.funding_source_to_dict(retirement.funding_sources[0])["max_share_bp"] == 4000
    # Replacing one's own 60% does not add it twice.
    _plan(db, pc, (2, 5000, 6000))
    # 60% and 50% on different accounts have no shared total.
    _plan(db, retirement, (4, 10000, 5000))
    assert isinstance(models.CapsuleFundingSource.__table__.c.max_share_bp.type, BasisPoints)


@pytest.mark.parametrize("share", [-1, 10001, 1.5, True])
def test_share_input_rejects_invalid_basis_points(share):
    with pytest.raises(ValidationError):
        schemas.CapsuleFundingSourceInput(account_id=2, max_share_bp=share)


def test_clamp_separates_posted_pending_and_rejected(db):
    owner = _owner(db, target=10000)
    _plan(db, owner, (2, 10000, None))
    rule = _rule(db, owner, amount=7000, destination=2)
    _salary(db)
    first = db.query(models.TransactionProposal).one()
    assert first.status == "pending"
    assert _jpy_claim(db, 1, owner.id) == 0
    assert _preview(db)[0].amount_minor == 3000
    ledger.approve_proposal(db, first, actor_client_id=1)
    db.commit()
    assert _jpy_claim(db, 1, owner.id) == 7000
    _salary(db)
    second = db.query(models.TransactionProposal).filter_by(status="pending").one()
    assert second.amount_minor == 3000
    assert _preview(db) == []
    assert _jpy_claim(db, 1, owner.id) == 7000  # pending is not money
    ledger.reject_proposal(db, second, actor_client_id=1)
    db.commit()
    assert _preview(db)[0].amount_minor == 3000
    _salary(db)
    third = db.query(models.TransactionProposal).filter_by(status="pending").one()
    ledger.approve_proposal(db, third, actor_client_id=1)
    db.commit()
    assert _jpy_claim(db, 1, owner.id) == 10000
    assert _preview(db) == []
    assert _rule_to_dict(rule)["destination_account_id"] == 2


def test_claim_reads_posted_journal_signed_legs_and_is_client_scoped(db):
    owner = _owner(db)
    _rule(db, owner)
    _salary(db)
    proposal = db.query(models.TransactionProposal).one()
    ledger.approve_proposal(db, proposal, actor_client_id=1)
    db.commit()
    assert _jpy_claim(db, 1, owner.id, 2) == 10000
    assert _jpy_claim(db, 1, owner.id, 1) == 0
    assert _jpy_claim(db, 2, owner.id) == 0
    assert _jpy_claim(db, 1, owner.id + 999) == 0
    assert not db.new and not db.dirty and not db.deleted
    # Journal changes must be read; a proposal's frozen amount is not the fact.
    tx = db.get(models.Transaction, proposal.posted_transaction_id)
    ledger.update_transaction(db, tx.id, schemas.TransactionUpdate(amount=8000), 1, commit=False)
    db.flush()
    assert _jpy_claim(db, 1, owner.id, 2) == _jpy_claim(db, 1, owner.id) == 8000
    assert proposal.amount_minor == 10000
    # Editing today's intent cannot erase yesterday's attributed movement.
    _plan(db, owner, (4, 100000, None))
    assert _jpy_claim(db, 1, owner.id) == 8000


def test_multiple_rules_for_one_capsule_share_the_same_headroom(db):
    owner = _owner(db, target=10000)
    _rule(db, owner, 7000)
    _rule(db, owner, 7000)
    assert [s.amount_minor for s in _preview(db)] == [7000, 3000]
    _salary(db)
    assert sum(p.amount_minor for p in db.query(models.TransactionProposal)) == 10000


def test_amend_re_evaluates_even_when_old_reservation_was_rejected(db):
    owner = _owner(db)
    _rule(db, owner, amount=10, amount_type="percentage")
    salary = _salary(db)
    first = db.query(models.TransactionProposal).one()
    ledger.reject_proposal(db, first, actor_client_id=1)
    db.commit()
    amend_entry(db, 1, salary.id, schemas.TransactionUpdate(amount=100000))
    proposals = db.query(models.TransactionProposal).order_by(models.TransactionProposal.id).all()
    assert [(p.status, p.amount_minor) for p in proposals] == [("rejected", 20000), ("pending", 10000)]


def test_clamp_and_routing_keep_large_minor_units_exact(db):
    owner = _owner(db)
    _plan(db, owner, (2, 1, None), (4, 1, None), (5, 1, None))
    rule = _rule(db, owner)
    exact = 2**53 + 7
    owner.target_amount_minor = rule.amount_minor = exact
    db.commit()
    assert sum(s.amount_minor for s in _preview(db)) == exact
    _salary(db)
    proposals = db.query(models.TransactionProposal).all()
    assert sum(p.amount_minor for p in proposals) == exact
    for proposal in proposals:
        ledger.approve_proposal(db, proposal, actor_client_id=1)
    db.commit()
    assert _jpy_claim(db, 1, owner.id) == exact
    owner.target_amount_minor += 1
    db.commit()
    assert sum(s.amount_minor for s in _preview(db)) == 1


def test_migration_both_directions_preserve_plan_and_rule_rows():
    path = Path(__file__).parents[1] / "alembic/versions/20261013_0055_capsule_funding_routing.py"
    spec = importlib.util.spec_from_file_location("f1b_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261013_0055"
    assert migration.down_revision == "20261013_0054"
    metadata = sa.MetaData()
    accounts = sa.Table("accounts", metadata, sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("max_capsule_share_bp", sa.Integer, nullable=True))
    sources = sa.Table("capsule_funding_sources", metadata, sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")),
                       sa.Column("target_amount_minor", sa.BigInteger))
    rules = sa.Table("capsule_rules", metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("capsule_id", sa.Integer), sa.Column("amount_minor", sa.BigInteger))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(accounts.insert(), {"id": 1})
            connection.execute(sources.insert(), {"id": 1, "account_id": 1, "target_amount_minor": 12345})
            connection.execute(rules.insert(), {"id": 1, "capsule_id": 7, "amount_minor": 5000})
        for direction in ["upgrade", "downgrade", "upgrade"]:
            with engine.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    getattr(migration, direction)()
            inspector = sa.inspect(engine)
            upgraded = direction == "upgrade"
            assert ("max_capsule_share_bp" in {c["name"] for c in inspector.get_columns("accounts")}) != upgraded
            assert ("max_share_bp" in {c["name"] for c in inspector.get_columns("capsule_funding_sources")}) == upgraded
            assert ("destination_account_id" in {c["name"] for c in inspector.get_columns("capsule_rules")}) == upgraded
            if upgraded:
                assert next(c for c in inspector.get_columns("capsule_funding_sources") if c["name"] == "max_share_bp")["nullable"]
                assert next(c for c in inspector.get_columns("capsule_rules") if c["name"] == "destination_account_id")["nullable"]
                assert any(fk["constrained_columns"] == ["destination_account_id"] and fk["referred_table"] == "accounts"
                           for fk in inspector.get_foreign_keys("capsule_rules"))
            with engine.connect() as connection:
                assert connection.scalar(sa.text("SELECT target_amount_minor FROM capsule_funding_sources")) == 12345
                assert connection.scalar(sa.text("SELECT amount_minor FROM capsule_rules")) == 5000
                if upgraded:
                    assert connection.scalar(sa.text("SELECT max_share_bp FROM capsule_funding_sources")) is None
                    assert connection.scalar(sa.text("SELECT destination_account_id FROM capsule_rules")) is None
    finally:
        engine.dispose()


def test_a_claim_is_kept_per_currency_and_a_foreign_reservation_is_not_clamped(db):
    """claimed_minor answers per currency, and the clamp only reads its own.

    A capsule's target is denominated in the client's currency. A reservation
    triggered by a dollar payment is counted in cents, so it cannot be
    subtracted from a yen target -- that is the operation B5 removed from the
    account balance. Converting instead would make a reservation's size depend
    on an exchange rate. So the foreign reservation happens, is recorded in its
    own currency, and is left out of the clamp; F3 reports it.
    """
    owner = _owner(db, target=10000)
    _plan(db, owner, (2, 10000, None))
    _rule(db, owner, amount=4000, destination=2)

    # Yen first. record_entry already applies the rules, so this queues one
    # 4000 reservation and leaves 6000 of headroom.
    salary = _salary(db)
    db.flush()
    assert _jpy_claim(db, 1, owner.id) == 0  # queued, not posted
    pending = db.query(models.TransactionProposal).one()
    assert (pending.status, pending.currency, pending.amount_minor) == ("pending", "JPY", 4000)

    dollars = record_entry(db, 1, schemas.TransactionCreate(
        date=WHEN, description="Dollar salary", amount=2000, currency="USD",
        legs=[schemas.TransactionLeg(account_id=1, debit=2000),
              schemas.TransactionLeg(account_id=3, credit=2000)],
    ))
    capsule.apply_capsule_rules_for_transaction(db, dollars, commit=False)
    db.flush()

    foreign = db.query(models.TransactionProposal).filter_by(currency="USD").one()
    # "Reserve 4000" against a dollar payment reserves 4000 dollars: the number
    # is re-read, not converted. The pending yen reservation did not reduce it,
    # because there is no common unit to subtract in.
    assert foreign.amount_minor == 400000
    assert ledger.approve_proposal(db, foreign, actor_client_id=None) is not None
    db.flush()

    claims = capsule.claimed_minor(db, 1, owner.id)
    assert claims == {"USD": 400000}
    assert capsule.claimed_minor(db, 1, owner.id, 2) == {"USD": 400000}
    # The yen clamp is unchanged by it: 10000 target less the 4000 still pending.
    assert _jpy_claim(db, 1, owner.id) == 0
    # Evaluating the same yen trigger again still offers 4000: the headroom is
    # 10000 less the 4000 pending, and the dollars are not in it.
    specs = capsule.capsule_transfer_specs(
        db, 1, entries=list(salary.journal_entries),
        description="Salary", amount=200000, currency="JPY",
    )
    assert [spec.amount_minor for spec in specs] == [4000]
