"""The database role matrix (WP32 W5): complete, least-privilege, and turned into the right SQL."""
import io

from app import db_access as access, models  # noqa: F401
from app.database import Base
from app.maintenance import db_grants

from tests.test_table_ownership import OWNERS

ADMIN_OWNED_SERVICES = {"services/admin_auth_service", "services/admin_audit_service", "services/system_settings_service"}


def test_every_table_is_in_the_matrix():
    tables = {table.name for table in Base.metadata.sorted_tables}
    assert tables == set(access.TABLE_ACCESS), (
        "Every table needs a decision in app/db_access.py: missing "
        f"{sorted(tables - set(access.TABLE_ACCESS))}, unknown {sorted(set(access.TABLE_ACCESS) - tables)}"
    )


def test_only_known_roles_and_privileges():
    for table, roles in access.TABLE_ACCESS.items():
        assert set(roles) <= set(access.APP_ROLES), table
        for granted in roles.values():
            assert granted <= access.FULL, table
            assert "SELECT" in granted, f"{table}: a role that writes must also read"


def test_user_app_cannot_touch_the_administration():
    for table, service in OWNERS.items():
        if service in ADMIN_OWNED_SERVICES and table != "system_settings":
            assert access.privileges(table, access.USER_APP) == frozenset(), table
    assert access.privileges("system_settings", access.USER_APP) == access.READ


def test_user_app_writes_every_table_its_services_own():
    for table, service in OWNERS.items():
        if service in ADMIN_OWNED_SERVICES:
            continue
        assert access.can_write(table, access.USER_APP), f"{table} ({service}) is written by the user side"


def test_admin_app_writes_the_admin_tables_and_reads_everything():
    for table in access.TABLE_ACCESS:
        assert "SELECT" in access.privileges(table, access.ADMIN_APP), table
    for table in access.ADMIN_TABLES:
        assert access.privileges(table, access.ADMIN_APP) == access.FULL, table
    assert {"INSERT", "UPDATE"} <= access.privileges("clients", access.ADMIN_APP)
    assert "DELETE" in access.privileges("client_mfa_settings", access.ADMIN_APP)


def test_audit_log_is_append_only():
    for role in access.APP_ROLES:
        assert not access.privileges("admin_audit_logs", role) & {"UPDATE", "DELETE"}


def test_user_app_cannot_change_account_status():
    columns = set(access.COLUMN_UPDATES[("clients", access.USER_APP)])
    assert "UPDATE" not in access.privileges("clients", access.USER_APP)
    assert not columns & {"is_active", "approval_pending", "suspended_reason", "id", "username"}
    client_columns = {column.name for column in models.Client.__table__.columns}
    assert columns <= client_columns


def test_generated_sql():
    sql = db_grants.statements(db_grants.conventional_sequences(), database="finance_ide")
    assert sql[0] == "GRANT USAGE ON SCHEMA public TO am_user_app, am_admin_app"
    assert 'GRANT CONNECT ON DATABASE "finance_ide" TO am_user_app, am_admin_app' in sql
    assert 'REVOKE ALL ON TABLE public."clients" FROM am_user_app, am_admin_app' in sql
    assert 'GRANT SELECT, INSERT ON TABLE public."clients" TO am_user_app' in sql
    assert any(line.startswith('GRANT UPDATE ("name", "email", "password_hash"') and line.endswith('ON TABLE public."clients" TO am_user_app')
               for line in sql)
    assert 'GRANT SELECT, INSERT ON TABLE public."admin_audit_logs" TO am_admin_app' in sql
    assert not any('public."admin_users" TO am_user_app' in line for line in sql)
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."transactions" TO am_user_app' in sql
    assert 'GRANT SELECT ON TABLE public."transactions" TO am_admin_app' in sql
    assert 'GRANT USAGE, SELECT ON SEQUENCE public."clients_id_seq" TO am_user_app, am_admin_app' in sql
    # The migrations' table: read-only for both (a backup's manifest records the schema revision).
    assert 'GRANT SELECT ON TABLE public."alembic_version" TO am_user_app' in sql
    assert 'GRANT SELECT ON TABLE public."alembic_version" TO am_admin_app' in sql
    # The string-keyed tables have no sequence.
    assert not any("admin_sessions_id_seq" in line for line in sql)


def test_print_only_runs_without_a_database():
    out = io.StringIO()
    assert db_grants.main(["--print-only"], out=out) == 0
    assert out.getvalue().count(";\n") > 40
