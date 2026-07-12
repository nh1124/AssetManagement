import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app import schemas
from backend.app.main import app


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "mcp" / "contracts" / "write-tools.json"
MCP_TOOL_PATH = ROOT / "mcp" / "src" / "tools"


def load_contracts() -> list[dict]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def resolve_schema(openapi: dict, schema: dict) -> dict:
    if "$ref" in schema:
        ref = schema["$ref"]
        _, _, name = ref.rpartition("/")
        return resolve_schema(openapi, openapi["components"]["schemas"][name])
    if "allOf" in schema:
        merged: dict = {"properties": {}, "required": []}
        for part in schema["allOf"]:
            resolved = resolve_schema(openapi, part)
            merged["properties"].update(resolved.get("properties", {}))
            merged["required"].extend(resolved.get("required", []))
        return merged
    return schema


def request_body_schema(openapi: dict, contract: dict) -> dict | None:
    operation = openapi["paths"][contract["path"]][contract["method"]]
    request_body = operation.get("requestBody")
    if not request_body:
        return None
    schema = request_body["content"]["application/json"]["schema"]
    if contract["body"] == "array":
        schema = schema["items"]
    return resolve_schema(openapi, schema)


def test_contract_manifest_exists_and_is_nonempty():
    contracts = load_contracts()
    assert contracts
    assert {contract["tool"] for contract in contracts} >= {
        "monthly_plan_lines_save_batch",
        "products_update",
        "recurring_update",
        "recurring_process_due",
        "data_import_replace_current_client",
        "clients_update_settings",
        "clients_update_gemini_key",
    }


def test_every_registered_mutation_tool_is_in_contract_manifest():
    registered_mutations: set[str] = set()
    tool_block_pattern = re.compile(
        r'server\.registerTool\(\s*["\'](?P<tool>[^"\']+)["\'](?P<body>.*?)'
        r'(?=\n\s*server\.registerTool\(|\Z)',
        re.DOTALL,
    )
    for source_path in MCP_TOOL_PATH.glob("*.ts"):
        source = source_path.read_text(encoding="utf-8")
        for match in tool_block_pattern.finditer(source):
            if re.search(r"readOnlyHint\s*:\s*false", match.group("body")):
                registered_mutations.add(match.group("tool"))

    manifested_tools = {contract["tool"] for contract in load_contracts()}
    assert registered_mutations <= manifested_tools
    assert "clients_create" not in registered_mutations
    assert "capsules_process" not in registered_mutations


@pytest.mark.parametrize("contract", load_contracts(), ids=lambda c: f"{c['tool']} {c['method'].upper()} {c['path']}")
def test_mcp_write_contract_matches_backend_openapi(contract: dict):
    openapi = app.openapi()
    assert contract["path"] in openapi["paths"]
    assert contract["method"] in openapi["paths"][contract["path"]]

    if contract["body"] in {"none", "raw"}:
        return

    schema = request_body_schema(openapi, contract)
    assert schema is not None
    properties = set(schema.get("properties", {}))

    allowed_fields = set(contract.get("allowed_fields", []))
    required_fields = set(contract.get("required_fields", []))
    forbidden_fields = set(contract.get("forbidden_fields", []))

    assert allowed_fields <= properties
    assert required_fields <= properties
    assert forbidden_fields.isdisjoint(properties)
    assert forbidden_fields.isdisjoint(allowed_fields)


def test_monthly_plan_line_batch_update_rejects_priority_extra_field():
    with pytest.raises(ValidationError):
        schemas.MonthlyPlanLineBatchUpdate(
            id=1,
            target_period="2026-06",
            line_type="expense",
            priority=2,
        )


def test_partial_update_schemas_reject_extra_fields():
    with pytest.raises(ValidationError):
        schemas.ProductUpdate(id=1)
    with pytest.raises(ValidationError):
        schemas.RecurringTransactionUpdate(priority=2)
