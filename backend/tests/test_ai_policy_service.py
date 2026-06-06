from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.routers import ai_operations
from backend.app.services.ai_policy_service import (
    AiOperationContext,
    evaluate_ai_operation,
    replace_client_policies,
    write_ai_audit_log,
)
from backend.app.utils.password import hash_password
from backend.app import schemas


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db):
    client = models.Client(
        id=1,
        name="Test User",
        username="tester",
        password_hash=hash_password("password123"),
        ai_config={},
        general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def test_default_policy_allows_read_preview() -> None:
    db = _session()
    try:
        client = _client(db)
        decision = evaluate_ai_operation(
            db,
            client.id,
            AiOperationContext(resource="transactions", action="preview", risk="low"),
        )

        assert decision.decision == "allowed"
        assert decision.mode == "allow_read"
    finally:
        db.close()


def test_default_policy_requires_approval_for_medium_write_and_critical_mfa() -> None:
    db = _session()
    try:
        client = _client(db)

        write_decision = evaluate_ai_operation(
            db,
            client.id,
            AiOperationContext(resource="monthly_plan_lines", action="update", risk="medium"),
        )
        critical_decision = evaluate_ai_operation(
            db,
            client.id,
            AiOperationContext(resource="data_transfer", action="import", risk="critical"),
        )

        assert write_decision.decision == "approval_required"
        assert write_decision.require_mfa is False
        assert critical_decision.decision == "approval_required"
        assert critical_decision.require_mfa is True
    finally:
        db.close()


def test_explicit_policy_denies_operation() -> None:
    db = _session()
    try:
        client = _client(db)
        replace_client_policies(db, client.id, [{
            "resource": "transactions",
            "action": "create",
            "risk": "low",
            "mode": "deny",
            "require_mfa": False,
        }])

        decision = evaluate_ai_operation(
            db,
            client.id,
            AiOperationContext(resource="transactions", action="create", risk="low"),
        )

        assert decision.decision == "denied"
        assert decision.policy_id is not None
    finally:
        db.close()


def test_allow_execute_policy_with_mfa_requires_verified_mfa() -> None:
    db = _session()
    try:
        client = _client(db)
        replace_client_policies(db, client.id, [{
            "resource": "exchange_rates",
            "action": "update",
            "risk": "low",
            "mode": "allow_execute",
            "require_mfa": True,
        }])

        missing_mfa = evaluate_ai_operation(
            db,
            client.id,
            AiOperationContext(resource="exchange_rates", action="update", risk="low", mfa_verified=False),
        )
        verified = evaluate_ai_operation(
            db,
            client.id,
            AiOperationContext(resource="exchange_rates", action="update", risk="low", mfa_verified=True),
        )

        assert missing_mfa.decision == "denied"
        assert missing_mfa.require_mfa is True
        assert verified.decision == "allowed"
    finally:
        db.close()


def test_audit_log_redacts_sensitive_values() -> None:
    db = _session()
    try:
        client = _client(db)
        context = AiOperationContext(
            source="mcp_http",
            tool_name="clients_update_key",
            resource="ai_settings",
            action="update",
            risk="critical",
            mcp_client_id="mcp_test_client",
            request_summary={
                "gemini_api_key": "secret-value",
                "nested": {"password": "password123", "safe": "visible"},
            },
        )
        decision = evaluate_ai_operation(db, client.id, context)

        log = write_ai_audit_log(
            db,
            client.id,
            context,
            decision,
            result={"access_token": "token-value", "status": "blocked"},
        )

        assert log.request_summary["gemini_api_key"] == "[redacted]"
        assert log.mcp_client_id == "mcp_test_client"
        assert log.request_summary["nested"]["password"] == "[redacted]"
        assert log.request_summary["nested"]["safe"] == "visible"
        assert log.result_summary["access_token"] == "[redacted]"
    finally:
        db.close()


def test_policy_router_replaces_and_lists_policies() -> None:
    db = _session()
    try:
        client = _client(db)
        payload = [
            schemas.AiOperationPolicyCreate(
                resource="transactions",
                action="create",
                risk="medium",
                mode="require_approval",
                require_mfa=False,
            ),
            schemas.AiOperationPolicyCreate(
                resource="data_transfer",
                action="import",
                risk="critical",
                mode="deny",
                require_mfa=True,
            ),
        ]

        saved = ai_operations.put_ai_policies(payload, db, client)
        listed = ai_operations.get_ai_policies(db, client)

        assert len(saved) == 2
        assert [policy.resource for policy in listed] == ["data_transfer", "transactions"]
    finally:
        db.close()
