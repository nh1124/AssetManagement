"""The surviving source kind keeps generated and manual identities separate."""

from __future__ import annotations

from app.services.money_storage import minor_fields


try:
    from backend.app import models
    from backend.app.services.budget_lines import assign_plan_line_identity, line_identity_key, plan_line_identity_key
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models
    from app.services.budget_lines import assign_plan_line_identity, line_identity_key, plan_line_identity_key


def _line(**overrides):
    fields = dict(
        plan_id=2,
        target_period="2026-05",
        source="manual",
        source_kind="manual",
        line_type="allocation",
        target_type="account",
        target_id=34,
        account_id=34,
        source_account_id=40,
        name="Savings",
        cash_treatment="auto",
    )
    fields.update(overrides)
    return models.MonthlyPlanLine(**minor_fields(fields, "JPY", 'amount'))


def test_identity_has_ten_elements_and_source_kind():
    key = line_identity_key(_line())
    assert len(key) == 10
    assert key[2] == "manual"
    # A user's record is told apart by its name (WP27): several may share an account and section.
    assert key == (2, "2026-05", "manual", "allocation", "account", 34, 40, 34, "savings", "auto")


def test_source_kind_alone_separates_identities():
    assert plan_line_identity_key(_line(source_kind="capsule")) != plan_line_identity_key(_line())


def test_capsule_and_manual_on_same_account_have_distinct_identities():
    capsule = _line(
        source="capsule",
        source_kind="capsule",
        target_type="capsule",
        target_id=7,
    )
    manual = _line()
    assert capsule.account_id == manual.account_id
    assert capsule.target_period == manual.target_period
    assert capsule.line_type == manual.line_type
    assert capsule.name == manual.name
    assert plan_line_identity_key(capsule) != plan_line_identity_key(manual)


def test_assign_identity_retains_kind_without_source_id():
    line = _line(
        source="capsule",
        source_kind=None,
        target_type="capsule",
        target_id=7,
    )
    assign_plan_line_identity(line)
    assert line.source_kind == "capsule"
    assert line.identity_key == plan_line_identity_key(line)
    assert not hasattr(line, "source_id")
