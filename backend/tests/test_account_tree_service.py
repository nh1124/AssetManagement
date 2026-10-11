from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import accounts as router
from backend.app.services import ledger_service as ledger
from backend.app.services.ledger_valuation import calculate_account_valued_balances
from backend.app.workflows.ledger_entry_workflow import record_entry


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="account-tree", ai_config={}, general_settings={}),
        models.Client(id=2, name="other", ai_config={}, general_settings={}),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _account(db, name="parent", account_type="asset", client_id=1, **data):
    return ledger.create_account(db, client_id, dict(name=name, account_type=account_type, **data))


def _refusal(status, detail, operation):
    with pytest.raises(HTTPException) as exc:
        operation()
    assert (exc.value.status_code, exc.value.detail) == (status, detail)


def test_parent_none_allows_a_root(db):
    ledger._validate_parent(db, 1, "asset", None)


def test_parent_cannot_be_the_account_itself(db):
    parent = _account(db)
    _refusal(400, "Account cannot be its own parent", lambda:
             ledger._validate_parent(db, 1, "asset", parent.id, account_id=parent.id))


def test_parent_must_exist(db):
    _refusal(404, "Parent account not found", lambda:
             ledger._validate_parent(db, 1, "asset", 999999))


def test_parent_must_belong_to_the_client(db):
    parent = _account(db, client_id=2)
    _refusal(404, "Parent account not found", lambda:
             ledger._validate_parent(db, 1, "asset", parent.id))


def test_parent_must_be_active(db):
    parent = _account(db)
    parent.is_active = False
    db.commit()
    _refusal(404, "Parent account not found", lambda:
             ledger._validate_parent(db, 1, "asset", parent.id))


def test_parent_must_have_the_same_account_type(db):
    parent = _account(db)
    _refusal(400, "Parent account must have the same account_type", lambda:
             ledger._validate_parent(db, 1, "expense", parent.id))


def test_parent_chain_must_not_already_contain_a_cycle(db):
    first = _account(db, name="first")
    second = _account(db, name="second", parent_id=first.id)
    first.parent_id = second.id
    db.commit()
    _refusal(400, "Account hierarchy cycle detected", lambda:
             ledger._validate_parent(db, 1, "asset", first.id))


def test_parent_chain_must_not_reach_the_account_being_updated(db):
    root = _account(db)
    child = _account(db, name="child", parent_id=root.id)
    _refusal(400, "Account hierarchy cycle detected", lambda:
             ledger.update_account(db, 1, root.id, {"parent_id": child.id}))
    assert root.parent_id is None


def test_parent_chain_accepts_a_root_and_valid_ancestors(db):
    root = _account(db)
    child = _account(db, name="child", parent_id=root.id)
    ledger._validate_parent(db, 1, "asset", root.id)
    ledger._validate_parent(db, 1, "asset", child.id)


@pytest.mark.parametrize("ancestor_kind", ["missing", "other_client"])
def test_parent_chain_stops_at_an_unavailable_ancestor(db, ancestor_kind):
    parent = _account(db)
    parent.parent_id = 999999 if ancestor_kind == "missing" else _account(db, client_id=2).id
    db.commit()
    ledger._validate_parent(db, 1, "asset", parent.id)


def test_parent_chain_checks_inactive_ancestors_for_cycles(db):
    root = _account(db)
    child = _account(db, name="child", parent_id=root.id)
    root.is_active = False
    root.parent_id = child.id
    db.commit()
    _refusal(400, "Account hierarchy cycle detected", lambda:
             ledger._validate_parent(db, 1, "asset", child.id))


def test_parent_chain_does_not_revalidate_ancestor_types(db):
    root = _account(db, name="root", account_type="expense")
    parent = _account(db)
    parent.parent_id = root.id
    db.commit()
    ledger._validate_parent(db, 1, "asset", parent.id)


def test_create_child_of_a_different_type_is_rejected_without_writing(db):
    parent = _account(db)
    before = db.query(models.Account).count()
    _refusal(400, "Parent account must have the same account_type", lambda:
             _account(db, name="child", account_type="expense", parent_id=parent.id))
    assert db.query(models.Account).count() == before
    client = db.get(models.Client, 1)
    _refusal(400, "Parent account must have the same account_type", lambda:
             router.create_account(router.AccountCreate(
                 name="child", account_type="expense", parent_id=parent.id,
             ), db=db, current_client=client))


def test_delete_deactivates_only_the_account_and_preserves_all_history(db):
    cash = _account(db, name="cash")
    food = _account(db, name="food", account_type="expense")
    transaction = record_entry(db, 1, schemas.TransactionCreate(
        date=date(2026, 10, 11), description="lunch", amount=300,
        from_account_id=cash.id, to_account_id=food.id,
    ))
    before = [(leg.id, leg.transaction_id, leg.account_id, leg.debit, leg.credit)
              for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)]
    balance = cash.balance
    assert ledger.delete_account(db, 1, cash.id) is True
    db.refresh(cash)
    assert cash.is_active is False
    assert cash.balance == balance == -300
    assert db.query(models.Transaction).one().id == transaction.id
    assert [(leg.id, leg.transaction_id, leg.account_id, leg.debit, leg.credit)
            for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)] == before
    assert db.get(models.Account, cash.id) is cash
    assert ledger.delete_account(db, 1, cash.id) is True


def test_delete_refuses_active_children(db):
    root = _account(db)
    _account(db, name="child", parent_id=root.id)
    _refusal(400, "Account has child accounts", lambda: ledger.delete_account(db, 1, root.id))
    assert root.is_active is True


@pytest.mark.parametrize("reference", ["default_from_account_id", "default_to_account_id"])
def test_delete_refuses_active_templates_in_either_direction(db, reference):
    root = _account(db)
    db.add(models.QuickTemplate(client_id=1, tray="test", name="test", template_kind="test",
                                **{reference: root.id}))
    db.commit()
    _refusal(400, "Account is used by active quick templates. Delete or update those templates first.",
             lambda: ledger.delete_account(db, 1, root.id))
    assert root.is_active is True


def test_delete_ignores_inactive_children_and_inactive_or_other_client_templates(db):
    root = _account(db)
    child = _account(db, name="child", parent_id=root.id)
    child.is_active = False
    db.add_all([
        models.QuickTemplate(client_id=1, tray="test", name="inactive", template_kind="test",
                             default_from_account_id=root.id, is_active=False),
        models.QuickTemplate(client_id=2, tray="test", name="other", template_kind="test",
                             default_to_account_id=root.id),
    ])
    db.commit()
    assert ledger.delete_account(db, 1, root.id) is True
    assert db.query(models.QuickTemplate).count() == 2
    assert child.parent_id == root.id


@pytest.mark.parametrize("missing", ["unknown", "other_client"])
def test_update_and_delete_return_missing_without_modifying_other_clients(db, missing):
    account = _account(db, client_id=2)
    account_id = 999999 if missing == "unknown" else account.id
    assert ledger.update_account(db, 1, account_id, {"name": "changed"}) is None
    assert ledger.delete_account(db, 1, account_id) is False
    assert account.name == "parent"
    assert account.is_active is True


def test_two_level_tree_preserves_endpoint_structure_and_rollup(db):
    root = _account(db, name="bank")
    child = _account(db, name="wallet", parent_id=root.id)
    income = _account(db, name="salary", account_type="income")
    for source, target, amount in [(income, root, 1000), (root, child, 300)]:
        record_entry(db, 1, schemas.TransactionCreate(
            date=date(2026, 10, 11), description="tree balances", amount=amount,
            from_account_id=source.id, to_account_id=target.id,
        ))
    # Keep the assertion focused on this tree while default seeding retains its behavior.
    for account in db.query(models.Account).filter(models.Account.id.notin_([root.id, child.id, income.id])):
        account.is_active = False
    db.commit()
    rows = ledger.list_accounts(db, 1, ordered=False)
    tree = router._build_tree(rows, calculate_account_valued_balances(db, rows))

    def expected(account, balance, rollup, children):
        return dict(
            id=account.id, name=account.name, account_type=account.account_type,
            balance=balance, rollup_balance=rollup, parent_id=account.parent_id,
            expected_return=0.0, role="unassigned", role_target_amount=None,
            liability_closing_day=None, liability_payment_day=None,
            liability_payment_month_offset=0, liability_payment_policy="full",
            liability_minimum_payment=None, liability_fixed_payment_amount=None,
            liability_installment_months=None, liability_revolving_rate=None,
            is_active=True, children=children,
        )

    assert tree == {
        "asset": [expected(root, 700, 1000, [expected(child, 300, 300, [])])],
        "liability": [], "income": [expected(income, 1000, 1000, [])], "expense": [],
    }
    assert router.get_account_tree(db=db, current_client=db.get(models.Client, 1)) == tree


@pytest.mark.parametrize("field,value,detail", [
    ("liability_closing_day", 0, "liability_closing_day must be between 1 and 31"),
    ("liability_payment_day", 32, "liability_payment_day must be between 1 and 31"),
    ("liability_payment_month_offset", -1, "liability_payment_month_offset must be between 0 and 24"),
    ("liability_payment_month_offset", 25, "liability_payment_month_offset must be between 0 and 24"),
    ("liability_installment_months", 0, "liability_installment_months must be positive"),
    ("liability_minimum_payment", -1, "liability_minimum_payment must not be negative"),
    ("liability_fixed_payment_amount", -1, "liability_fixed_payment_amount must not be negative"),
    ("liability_revolving_rate", -1, "liability_revolving_rate must not be negative"),
])
def test_liability_settings_preserve_each_range_refusal(db, field, value, detail):
    _refusal(400, detail, lambda: _account(db, account_type="liability", **{field: value}))


def test_liability_update_retains_default_reset_and_nonliability_strips_settings(db):
    liability = _account(db, account_type="liability", liability_payment_policy="fixed",
                         liability_payment_month_offset=2, liability_closing_day=31)
    ledger.update_account(db, 1, liability.id, {"name": "renamed"})
    assert (liability.liability_payment_policy, liability.liability_payment_month_offset) == ("full", 0)
    assert liability.liability_closing_day == 31
    asset = _account(db, name="asset", liability_closing_day=-10)
    assert asset.liability_closing_day is None
    ledger.update_account(db, 1, asset.id, {"liability_closing_day": 32})
    assert asset.liability_closing_day is None


def test_opening_balance_tolerance_and_update_balance_refusal_are_preserved(db):
    account = _account(db, balance=0.01)
    assert account.balance == 0
    _refusal(400, "Journal is the source of truth. Create an opening-balance transaction instead of setting account.balance.",
             lambda: _account(db, name="invalid", balance=0.02))
    _refusal(400, "Journal is the source of truth. Use transactions to change balances.",
             lambda: ledger.update_account(db, 1, account.id, {"balance": None}))


def test_account_crud_commit_false_leaves_changes_for_the_caller(db):
    existing = _account(db)
    account = ledger.create_account(db, 1, {"name": "pending", "account_type": "asset"}, commit=False)
    ledger.update_account(db, 1, existing.id, {"name": "changed"}, commit=False)
    assert ledger.delete_account(db, 1, existing.id, commit=False) is True
    pending_id = account.id
    db.rollback()
    assert db.get(models.Account, pending_id) is None
    assert existing.name == "parent"
    assert existing.is_active is True
