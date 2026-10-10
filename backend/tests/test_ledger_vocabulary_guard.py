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


def _model_classes() -> dict[str, set[str]]:
    """Every mapped class in models, with the keywords its constructor takes."""
    from sqlalchemy import inspect as sa_inspect

    classes: dict[str, set[str]] = {}
    for name in dir(models):
        candidate = getattr(models, name)
        if not isinstance(candidate, type) or not hasattr(candidate, "__tablename__"):
            continue
        try:
            mapper = sa_inspect(candidate)
        except Exception:  # pragma: no cover - not a mapped class
            continue
        classes[name] = set(mapper.attrs.keys()) | set(candidate.__table__.columns.keys())
    return classes


def _model_constructor_keywords(path: pathlib.Path):
    """`models.Thing(foo=...)` calls, as (class name, keyword, line)."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    creators = {"create_transaction"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            creators.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "create_transaction"
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in creators:
            # These parameters describe journal legs, not Transaction columns.
            excluded = {"legs", "from_account_id", "to_account_id"}
            for keyword in node.keywords:
                if keyword.arg is not None and keyword.arg not in excluded:
                    yield "Transaction", keyword.arg, node.lineno
        elif (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "models"
        ):
            for keyword in node.keywords:
                if keyword.arg is None:  # **kwargs, unknowable here
                    continue
                yield func.attr, keyword.arg, node.lineno


def test_no_model_is_constructed_with_a_field_it_does_not_have():
    """A dropped column passed as a keyword is a TypeError at runtime.

    That is how the add_recurring monthly action broke when
    recurring_transactions.type went: nothing read the attribute, so the
    attribute guard above stayed quiet, and no test applied that action.
    """
    known = _model_classes()
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        for class_name, keyword, lineno in _model_constructor_keywords(path):
            fields = known.get(class_name)
            if fields is None or keyword in fields:
                continue
            offenders.append(
                f"{path.relative_to(APP_DIR)}:{lineno} models.{class_name}({keyword}=...)"
            )
    assert not offenders, "model constructors pass unknown fields:\n" + "\n".join(offenders)
