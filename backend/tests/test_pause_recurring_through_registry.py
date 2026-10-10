import pytest

from test_recurring_requires_registry import db, models

try:
    from backend.app.services.action_bridge_service import _apply_pause_recurring
    from backend.app.services.registry_service import reconcile_registry_recurring_links, registry_to_recurring_data, sync_recurring_from_registry, upsert_registry_from_recurring_payload
    from backend.app.services.budget_context import BudgetContext
    from backend.app.services.budget_registry_lines import registry_plan_lines
except ModuleNotFoundError:
    from app.services.action_bridge_service import _apply_pause_recurring
    from app.services.registry_service import reconcile_registry_recurring_links, registry_to_recurring_data, sync_recurring_from_registry, upsert_registry_from_recurring_payload
    from app.services.budget_context import BudgetContext
    from app.services.budget_registry_lines import registry_plan_lines


def test_pause_deactivates_registry_and_survives_edit_and_reconcile(db):
    recurring = upsert_registry_from_recurring_payload(db, 1, {"name": "subscription", "amount": 1200})
    entry = db.get(models.RegistryEntry, recurring.source_registry_entry_id)
    action = models.MonthlyAction(
        client_id=1,
        payload={"recurring_id": recurring.id},
    )
    assert registry_plan_lines(BudgetContext(db, 1), "2026-10")
    assert _apply_pause_recurring(db, action) == {"recurring_id": recurring.id, "is_active": False}
    assert entry.is_active is False
    assert recurring.is_active is False
    assert registry_plan_lines(BudgetContext(db, 1), "2026-10") == []
    entry.amount = 1300
    sync_recurring_from_registry(db, entry)
    reconcile_registry_recurring_links(db, 1)
    assert recurring.is_active is False


@pytest.mark.parametrize("missing", ["definition", "owner"])
def test_pause_rejects_rows_outside_action_client(db, missing):
    recurring = upsert_registry_from_recurring_payload(db, 1, {"name": "subscription"})
    entry = db.get(models.RegistryEntry, recurring.source_registry_entry_id)
    if missing == "owner":
        entry.client_id = 2
        db.flush()
    action = models.MonthlyAction(
        client_id=2 if missing == "definition" else 1,
        payload={"recurring_id": recurring.id},
    )
    with pytest.raises(ValueError, match="^Recurring transaction not found$"):
        _apply_pause_recurring(db, action)
    assert recurring.is_active is True


def test_registry_sync_defaults_new_definition_to_auto_post_and_preserves_manual_choice(db):
    entry = models.RegistryEntry(
        client_id=1,
        name="subscription",
        generate_recurring=True,
        budget_active=True,
    )
    db.add(entry)
    db.flush()
    assert "auto_post" not in registry_to_recurring_data(entry)
    sync_recurring_from_registry(db, entry)
    recurring = db.get(models.RecurringTransaction, entry.source_recurring_transaction_id)
    assert recurring.auto_post is True
    recurring = upsert_registry_from_recurring_payload(db, 1, {"auto_post": False}, recurring)
    entry.amount = 1300
    sync_recurring_from_registry(db, entry)
    reconcile_registry_recurring_links(db, 1)
    db.flush()
    db.refresh(recurring)
    assert recurring.auto_post is False
