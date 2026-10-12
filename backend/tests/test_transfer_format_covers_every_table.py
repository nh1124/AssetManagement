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
