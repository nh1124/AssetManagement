"""fx_service owns rates; ledger_valuation values the ledger.

A single debit-normal definition prevents ledger and valuation signs diverging.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
SERVICES_DIR = APP_DIR / "services"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def test_fx_service_references_only_rate_and_client_models():
    referenced = {
        node.attr
        for node in ast.walk(_parse(SERVICES_DIR / "fx_service.py"))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "models"
    }
    allowed = {"ExchangeRate", "Client"}
    assert referenced == allowed, (
        f"fx_service model boundary leaked: {sorted(referenced - allowed)}; "
        f"missing expected models: {sorted(allowed - referenced)}"
    )


def test_debit_normal_types_is_defined_only_in_ledger_service():
    definitions = []
    for path in sorted(APP_DIR.rglob("*.py")):
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                targets = [node.target]
            else:
                continue
            for target in targets:
                if any(
                    isinstance(name, ast.Name) and name.id == "DEBIT_NORMAL_TYPES"
                    for name in ast.walk(target)
                ):
                    definitions.append((path.relative_to(APP_DIR).as_posix(), node.lineno))
    assert len(definitions) == 1 and definitions[0][0] == "services/ledger_service.py", (
        f"DEBIT_NORMAL_TYPES must have one definition in ledger_service: {definitions}"
    )


def test_ledger_valuation_does_not_import_journal_legs():
    imports = []
    for node in ast.walk(_parse(SERVICES_DIR / "ledger_valuation.py")):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
            imports.extend(alias.name for alias in node.names)
    leaked = sorted(name for name in imports if "journal_legs" in name.split("."))
    assert not leaked, f"ledger_valuation must not import journal_legs: {leaked}"
