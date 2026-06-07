from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from backend.app import models
from backend.app.database import Base
from backend.app.routers import ai_operations
from backend.app.services.ai_context_service import (
    get_context_resource,
    list_context_resources,
)
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/ai/context/resources",
        "headers": [(b"x-mcp-client-id", b"test-mcp"), (b"x-mcp-tool-name", b"ai_context_resources")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    })


def _client_with_data(db):
    client = models.Client(
        id=1,
        name="Test User",
        username="tester",
        email="tester@example.com",
        password_hash=hash_password("password123"),
        ai_config={"gemini_api_key": "encrypted-secret-value"},
        general_settings={"currency": "JPY", "language": "ja"},
    )
    db.add(client)
    db.flush()
    db.add(models.ClientMfaSetting(client_id=client.id, totp_secret_encrypted="totp-secret", enabled=True))
    db.add(models.ClientRecoveryCode(client_id=client.id, code_hash="recovery-hash"))
    cash = models.Account(
        id=10,
        client_id=client.id,
        name="Cash",
        account_type="asset",
        balance=10000,
        role="operating",
    )
    food = models.Account(
        id=11,
        client_id=client.id,
        name="Food",
        account_type="expense",
        balance=0,
        role="unassigned",
    )
    db.add_all([cash, food])
    db.flush()
    db.add(models.Transaction(
        client_id=client.id,
        date=date(2026, 6, 1),
        description="Lunch",
        amount=1200,
        type="Expense",
        category="Food",
        currency="JPY",
        from_account_id=cash.id,
        to_account_id=food.id,
    ))
    db.commit()
    db.refresh(client)
    return client


def test_catalog_marks_data_export_unavailable_and_critical() -> None:
    resources = {item["resource"]: item for item in list_context_resources()}

    assert resources["summary"]["available"] is True
    assert resources["data_export"]["available"] is False
    assert resources["data_export"]["risk"] == "critical"


def test_context_settings_omits_secret_fields_and_values() -> None:
    db = _session()
    try:
        client = _client_with_data(db)

        payload = get_context_resource(db, client.id, "settings")
        text = json.dumps(payload, default=str)

        assert payload["resource"] == "settings"
        assert payload["data"]["ai_key_configured"] is True
        assert payload["data"]["mfa_enabled"] is True
        assert "password_hash" not in text
        assert "encrypted-secret-value" not in text
        assert "totp-secret" not in text
        assert "recovery-hash" not in text
    finally:
        db.close()


def test_context_recent_transactions_returns_safe_read_data() -> None:
    db = _session()
    try:
        client = _client_with_data(db)

        payload = get_context_resource(db, client.id, "transactions_recent", limit=10)

        assert payload["classification"] == "sensitive"
        assert payload["data"]["count"] == 1
        tx = payload["data"]["transactions"][0]
        assert tx["description"] == "Lunch"
        assert tx["from_account"]["name"] == "Cash"
        assert tx["to_account"]["name"] == "Food"
    finally:
        db.close()


def test_context_data_export_is_not_available() -> None:
    db = _session()
    try:
        client = _client_with_data(db)

        with pytest.raises(HTTPException) as excinfo:
            get_context_resource(db, client.id, "data_export")

        assert excinfo.value.status_code == 403
        assert excinfo.value.detail["risk"] == "critical"
    finally:
        db.close()


def test_context_resources_endpoint_writes_low_risk_audit_log() -> None:
    db = _session()
    try:
        client = _client_with_data(db)

        data = ai_operations.get_ai_context_resources(_request(), db, client)
        audit = db.query(models.AiAuditLog).one()

        assert any(item["resource"] == "summary" for item in data)
        assert audit.resource == "ai_context"
        assert audit.action == "read"
        assert audit.risk == "low"
        assert audit.mcp_client_id == "test-mcp"
        assert audit.request_summary["context_resource"] == "resources"
    finally:
        db.close()
