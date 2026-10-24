"""Every table is in the backup, or is excluded on purpose with a reason.

F1a added capsule_funding_sources and the backup format did not notice, so a
restore would have silently discarded the funding plan. Nothing failed: the
format is a hand-written list, and a new table simply is not on it.

This is the guard that would have caught it. Adding a table now forces a
decision -- carry it in the backup, or say here why it must not be -- and the
stale-entry test means an excluded table that later joins the format has to be
removed from the list deliberately.
"""
from __future__ import annotations

# Importing the package is what registers the tables on Base.metadata. Without
# it this guard passes while seeing almost no tables, which is how a guard ends
# up protecting nothing.
from app import models  # noqa: F401
from app.database import Base
from app.domain.transfer import DATA_COLLECTIONS


# A backup is portable user data. These tables are deliberately not in it, and
# each reason is about the data, not about the effort of adding it.
EXCLUDED: dict[str, str] = {
    "admin_users": "Installation administrator credentials are separate from portable user data.",
    "admin_user_permissions": "Installation capabilities must never travel in user backups.",
    "admin_sessions": "Installation sessions are credentials and must not be restored from user files.",
    "admin_audit_logs": "Administrative history belongs to the installation that produced it.",
    "system_settings": "Installation policy is not user data and must not be overwritten by an import.",
    "clients": (
        "The owner is the import's target, not part of its payload: export_client "
        "writes the client separately and import_client is told which client to "
        "write into."
    ),
    "client_mfa_settings": (
        "Holds the TOTP secret. A second factor that travels in a file the user "
        "can email themselves is not a second factor."
    ),
    "client_recovery_codes": (
        "Recovery codes are credentials for the same reason, and restoring them "
        "would revive codes the user has already spent."
    ),
    "mcp_oauth_clients": (
        "The AI apps registered with this installation's MCP server. They are not "
        "a person's data, and an id from another installation means nothing here."
    ),
    "mcp_connections": (
        "Grants to AI apps with their refresh-token hashes: credentials, and bound "
        "to this installation's MCP server. Restoring them would revive ended connections."
    ),
    "ai_operation_policies": (
        "What an AI may do is a property of this installation, not of the data. "
        "Restoring a permissive policy from an old backup would widen access "
        "without anyone deciding to."
    ),
    "ai_audit_logs": (
        "A log of what was read and when. It belongs to the installation that "
        "produced it; copying it into another would assert things that did not "
        "happen there."
    ),
    "ai_change_requests": (
        "A queue of pending decisions. Importing them would re-raise requests "
        "against rows whose ids the import has just reassigned."
    ),
    "transaction_proposals": (
        "A queue of pending reservations, which the capsule rules rebuild from "
        "the restored triggers. Importing them would duplicate what the rules "
        "propose and would carry trigger ids the import has reassigned."
    ),
    "notifications": (
        "Reminders are recomputed from the data, and 後で確認 / 見送り are decisions about "
        "this installation at a moment in time; restoring them would hide or revive "
        "reminders for reasons that no longer match the restored data."
    ),
    "alembic_version": (
        "The schema's own version, recorded in the manifest instead; a restore "
        "must not move the database to another revision."
    ),
}


def _tables() -> set[str]:
    tables = set(Base.metadata.tables)
    # test_models_package.py pins the exact count; this only has to be large
    # enough that an empty registry cannot make the comparisons below vacuous.
    assert len(tables) > 20, f"Model metadata is not loaded: {sorted(tables)}"
    return tables | {"alembic_version"}


def test_every_table_is_carried_or_excluded_on_purpose():
    unaccounted = sorted(_tables() - set(DATA_COLLECTIONS) - set(EXCLUDED))
    assert not unaccounted, (
        "These tables are neither in the backup format nor excluded from it:\n  "
        + "\n  ".join(unaccounted)
        + "\n\nAdd each to DATA_COLLECTIONS in app/domain/transfer.py, with its "
        "export and import, or to EXCLUDED here with the reason it must not be "
        "in a portable backup."
    )


def test_the_exclusion_list_has_no_stale_entries():
    tables = _tables()
    missing = sorted(set(EXCLUDED) - tables)
    assert not missing, f"Excluded table no longer exists: {missing}"
    carried = sorted(set(EXCLUDED) & set(DATA_COLLECTIONS))
    assert not carried, f"Excluded table is also in the backup format: {carried}"
    assert all(reason.strip() for reason in EXCLUDED.values())


def test_every_carried_collection_is_a_real_table():
    unknown = sorted(set(DATA_COLLECTIONS) - _tables())
    assert not unknown, f"The backup format names tables that do not exist: {unknown}"


def test_authentication_state_is_neither_exported_nor_imported():
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.routers.data_transfer import ImportPayload, import_client_data
    from app.services.data_transfer_service import export_client

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        client = models.Client(name="owner", username="owner", failed_login_count=3,
                               locked_until=datetime.utcnow() + timedelta(minutes=1),
                               tokens_valid_after=datetime.utcnow(), must_change_password=True)
        db.add(client)
        db.flush()
        setting = models.ClientMfaSetting(client_id=client.id, pending_totp_secret_encrypted="pending-secret", last_totp_step=123)
        db.add(setting)
        db.commit()
        fields = ("failed_login_count", "locked_until", "tokens_valid_after", "must_change_password")
        before = {field: getattr(client, field) for field in fields}
        document = export_client(db, client)
        assert not set(fields) & document["client"].keys()
        assert "client_mfa_settings" not in document["data"]
        assert "client_recovery_codes" not in document["data"]
        # A hand-edited client header cannot clear installation security state.
        document["client"].update(failed_login_count=0, locked_until=None, tokens_valid_after=None,
                                   must_change_password=False, pending_totp_secret_encrypted="injected", last_totp_step=None)
        import_client_data(ImportPayload(**document), db, client)
        db.refresh(client)
        db.refresh(setting)
        assert {field: getattr(client, field) for field in fields} == before
        assert setting.pending_totp_secret_encrypted == "pending-secret"
        assert setting.last_totp_step == 123
    engine.dispose()
