from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.domain import ai_operations as catalog
from backend.app.domain.errors import Conflict, Invalid, NotFound
from backend.app.routers import ai_operations
from backend.app.services.ai_policy_service import (
    AiOperationContext,
    list_operations,
    mcp_refusal,
    operation_mode,
    set_operation_mode,
    write_ai_audit_log,
)
from backend.app.utils.password import hash_password
from backend.app import schemas


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db, settings=None):
    client = models.Client(
        id=1,
        name="Test User",
        username="tester",
        password_hash=hash_password("password123"),
        general_settings=settings or {},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def test_defaults_keep_what_the_ai_could_do_before_wp36() -> None:
    """Reads and writes run; what posts to the ledger needed the transactions/create gate."""
    db = _session()
    try:
        client = _client(db)
        assert operation_mode(db, client.id, "accounts.read") == "allow"
        assert operation_mode(db, client.id, "capsules.create") == "allow"
        assert operation_mode(db, client.id, "transactions.create") == "approval"
        for key in ("transactions.update", "transactions.delete", "transaction_batches.create", "capsules.contribute",
                    "capsules.drawdown", "capsules.account_claim", "depreciations.record", "depreciations.amend",
                    "accounts.reconcile_adjust"):
            assert operation_mode(db, client.id, key) == "deny", key
    finally:
        db.close()


def test_each_operation_offers_only_the_modes_it_can_take() -> None:
    db = _session()
    try:
        client = _client(db)
        with pytest.raises(Invalid):
            set_operation_mode(db, client.id, "accounts.read", "approval", None)
        with pytest.raises(Invalid):
            set_operation_mode(db, client.id, "capsules.create", "approval", None)
        with pytest.raises(NotFound):
            set_operation_mode(db, client.id, "no.such", "allow", None)
        saved = set_operation_mode(db, client.id, "auto_transactions.update", "approval", "allow")
        assert (saved["mode"], saved["saved"], saved["modes"]) == ("approval", True, ["allow", "approval", "deny"])
        assert operation_mode(db, client.id, "auto_transactions.update") == "approval"
    finally:
        db.close()


def test_a_change_made_elsewhere_is_a_conflict() -> None:
    db = _session()
    try:
        client = _client(db)
        set_operation_mode(db, client.id, "capsules.create", "deny", "allow")
        with pytest.raises(Conflict) as error:
            set_operation_mode(db, client.id, "capsules.create", "allow", "allow")
        assert error.value.payload == {"error": "changed_elsewhere", "mode": "deny"}
        assert operation_mode(db, client.id, "capsules.create") == "deny"
    finally:
        db.close()


def test_the_list_covers_every_operation_by_section() -> None:
    db = _session()
    try:
        client = _client(db)
        set_operation_mode(db, client.id, "accounts.delete", "deny", None)
        listed = list_operations(db, client.id)
        keys = [entry["key"] for section in listed["sections"] for entry in section["operations"]]
        assert keys == [operation.key for section in catalog.SECTIONS
                        for operation in catalog.OPERATIONS if operation.section == section.key]
        assert sorted(keys) == sorted(catalog.BY_KEY)
        delete = next(entry for section in listed["sections"] for entry in section["operations"] if entry["key"] == "accounts.delete")
        assert (delete["mode"], delete["saved"], delete["ja"], delete["tools"]) == ("deny", True, "口座・勘定科目を削除する", ["accounts_delete"])
        assert "calc_future_value" in listed["local_tools"]
    finally:
        db.close()


@pytest.mark.parametrize("write_mode,saved,method,path,refusal", [
    ("direct_write", None, "POST", "/capsules/", None),
    ("direct_write", "deny", "POST", "/capsules/", "operation_denied"),
    ("direct_write", None, "POST", "/transactions/", "operation_needs_approval"),
    ("direct_write", None, "PUT", "/transactions/5", "operation_denied"),
    ("change_request", None, "POST", "/capsules/", "change_request_mode"),
    ("change_request", None, "POST", "/ai/change-requests", None),
    ("change_request", None, "GET", "/accounts/", None),
    ("direct_write", None, "GET", "/no-such-feature", "operation_unknown"),
    ("direct_write", None, "GET", "/ai/execution-settings", None),
])
def test_the_gateway_decides_by_the_operation(write_mode, saved, method, path, refusal) -> None:
    db = _session()
    try:
        client = _client(db, {"ai_operation": {"mcp_write_mode": write_mode}})
        if saved:
            set_operation_mode(db, client.id, catalog.match(method, path)[1].key, saved, None)
        assert mcp_refusal(db, client.id, method, path) == refusal
    finally:
        db.close()


def test_audit_log_redacts_sensitive_values() -> None:
    db = _session()
    try:
        client = _client(db)
        context = AiOperationContext(
            source="mcp_http",
            tool_name="clients_update_key",
            resource="settings",
            action="update",
            risk="medium",
            mcp_client_id="mcp_test_client",
            request_summary={
                "gemini_api_key": "secret-value",
                "nested": {"password": "password123", "safe": "visible"},
            },
        )
        log = write_ai_audit_log(
            db,
            client.id,
            context,
            "denied",
            result={"access_token": "token-value", "status": "blocked"},
        )

        assert log.request_summary["gemini_api_key"] == "[redacted]"
        assert log.mcp_client_id == "mcp_test_client"
        assert log.request_summary["nested"]["password"] == "[redacted]"
        assert log.request_summary["nested"]["safe"] == "visible"
        assert log.result_summary["access_token"] == "[redacted]"
    finally:
        db.close()


def test_execution_settings_are_stored_in_general_settings() -> None:
    db = _session()
    try:
        client = _client(db)
        payload = schemas.AiExecutionSettings(mcp_write_mode="change_request")

        saved = ai_operations.put_ai_execution_settings(payload, db, client)
        listed = ai_operations.get_ai_execution_settings(client)

        assert saved["mcp_write_mode"] == "change_request"
        assert listed["mcp_write_mode"] == "change_request"
        assert client.general_settings["ai_operation"]["mcp_write_mode"] == "change_request"
        assert listed["supported_change_request_operations"] == [
            "transactions.create", "plan_lines.update", "auto_transactions.create", "auto_transactions.update",
        ]
    finally:
        db.close()
