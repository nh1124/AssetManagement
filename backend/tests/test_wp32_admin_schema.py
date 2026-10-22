"""WP32 upgrade and downgrade preserve existing client data on SQLite."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import models


def test_migration_upgrade_defaults_constraints_and_downgrade():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261022_0090_admin_console.py"
    spec = importlib.util.spec_from_file_location("wp32", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261022_0089"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        conn.execute(sa.text("CREATE TABLE clients (id INTEGER PRIMARY KEY, username TEXT)"))
        conn.execute(sa.text("INSERT INTO clients VALUES (1, 'existing')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.execute(sa.text("SELECT username, approval_pending, suspended_reason FROM clients")).one() == ("existing", 0, None)
        new_tables = {"admin_users", "admin_user_permissions", "admin_sessions", "admin_audit_logs", "system_settings"}
        for table in new_tables:
            actual = {col["name"]: col for col in sa.inspect(conn).get_columns(table)}
            expected = models.Base.metadata.tables[table]
            assert set(actual) == set(expected.c.keys())
            for col in expected.c:
                assert actual[col.name]["nullable"] == col.nullable
                assert str(actual[col.name]["type"]) == str(col.type)
            assert {index["name"] for index in sa.inspect(conn).get_indexes(table)} == {index.name for index in expected.indexes}
        conn.execute(sa.text("INSERT INTO admin_users (id, username, password_hash, created_at, created_by) VALUES (1, 'owner', 'hash', CURRENT_TIMESTAMP, 'cli:test')"))
        assert conn.execute(sa.text("SELECT mfa_enabled, is_active, failed_login_count, must_change_password FROM admin_users")).one() == (0, 1, 0, 0)
        assert isinstance(sa.inspect(conn).get_columns("admin_users")[5]["type"], sa.BigInteger)
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert set(sa.inspect(conn).get_table_names()) == {"clients"}
        assert conn.execute(sa.text("SELECT * FROM clients")).one() == (1, "existing")
    engine.dispose()
