"""The ledger keeps its accounts in the legs, and nothing else.

Four fields were removed over P7-001 waves 1 to 3: transactions.type,
transactions.category, and the denormalised from_account_id / to_account_id
pair. Each one was a second place where an entry said what it touched, and
each could disagree with the legs. These tests fail if one comes back as a
column, which is how it would come back: a model attribute is enough for
reads and writes to spread again before anyone notices.
"""

from __future__ import annotations

import ast
import pathlib

from app import models

APP_DIR = pathlib.Path(models.__file__).parent
GONE = ("type", "category", "from_account_id", "to_account_id")


def test_transaction_model_has_no_summary_columns():
    for name in GONE:
        assert name not in models.Transaction.__table__.columns, (
            f"transactions.{name} is back; the legs are the accounts"
        )
        assert not hasattr(models.Transaction, name), (
            f"Transaction.{name} is back as a mapped attribute"
        )


def test_recurring_and_registry_do_not_name_a_ledger_type():
    assert "type" not in models.RecurringTransaction.__table__.columns
    assert "transaction_type" not in models.RegistryEntry.__table__.columns
    # The budget keeps its own axis: line_type disagreed with the ledger type
    # on 53 of 68 entries, which is why it is a separate field.
    assert "line_type" in models.RegistryEntry.__table__.columns


def _transaction_attribute_reads(path: pathlib.Path) -> list[str]:
    """`tx.from_account_id` and friends, where the holder is a transaction.

    Recurring transactions and registry entries keep a from/to pair of their
    own, so this looks at the name being read from rather than at the
    attribute alone.
    """
    # utf-8-sig: one service file carries a BOM.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    holders = {"tx", "transaction", "db_transaction"}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in GONE:
            continue
        value = node.value
        if isinstance(value, ast.Name) and value.id in holders:
            found.append(f"{path.name}:{node.lineno} {value.id}.{node.attr}")
        elif (
            isinstance(value, ast.Attribute)
            and value.attr == "Transaction"
            and isinstance(value.value, ast.Name)
            and value.value.id == "models"
        ):
            found.append(f"{path.name}:{node.lineno} models.Transaction.{node.attr}")
    return found


def test_no_service_or_router_reads_a_removed_field():
    offenders: list[str] = []
    for directory in ("services", "routers", "maintenance"):
        for path in sorted((APP_DIR / directory).rglob("*.py")):
            offenders.extend(_transaction_attribute_reads(path))
    assert not offenders, "removed transaction fields are referenced:\n" + "\n".join(offenders)
