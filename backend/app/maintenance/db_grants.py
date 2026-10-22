"""Apply the database privileges declared in app.db_access (WP32 W5).

Run as the table owner (am_owner) after the migrations, which is what the
``migrate`` compose service does:

    python -m app.maintenance.db_grants              # dry run: print the SQL (needs the database)
    python -m app.maintenance.db_grants --apply      # apply it in one transaction
    python -m app.maintenance.db_grants --print-only # print the SQL without a database

Idempotent: every table's privileges for the application roles are revoked and
granted again, so a privilege removed from the matrix disappears from the
database too.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import BigInteger, Integer, create_engine, text

from .. import models  # noqa: F401  (registers every table on Base.metadata)
from ..database import Base
from ..db_access import APP_ROLES, COLUMN_UPDATES, NON_MODEL_TABLES, TABLE_ACCESS

SCHEMA = "public"
ORDER = ("SELECT", "INSERT", "UPDATE", "DELETE")


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def table_name(table: str) -> str:
    return f"{SCHEMA}.{quote(table)}"


def serial_tables() -> list[str]:
    """Tables whose primary key is an integer id, i.e. that own an id sequence."""
    tables = []
    for table in Base.metadata.sorted_tables:
        key = list(table.primary_key.columns)
        if len(key) == 1 and key[0].name == "id" and isinstance(key[0].type, (Integer, BigInteger)):
            tables.append(table.name)
    return sorted(tables)


def conventional_sequences() -> dict[str, str]:
    return {table: f"{SCHEMA}.{quote(table + '_id_seq')}" for table in serial_tables()}


def statements(sequences: dict[str, str], database: str | None = None) -> list[str]:
    roles = ", ".join(APP_ROLES)
    sql = [f"GRANT USAGE ON SCHEMA {SCHEMA} TO {roles}"]
    if database:
        sql.append(f"GRANT CONNECT ON DATABASE {quote(database)} TO {roles}")
    matrix = {**NON_MODEL_TABLES, **TABLE_ACCESS}
    for table in sorted(matrix):
        sql.append(f"REVOKE ALL ON TABLE {table_name(table)} FROM {roles}")
        for role in APP_ROLES:
            granted = matrix[table].get(role, frozenset())
            if granted:
                sql.append(f"GRANT {', '.join(p for p in ORDER if p in granted)} ON TABLE {table_name(table)} TO {role}")
            columns = COLUMN_UPDATES.get((table, role))
            if columns:
                sql.append(f"GRANT UPDATE ({', '.join(quote(c) for c in columns)}) ON TABLE {table_name(table)} TO {role}")
        sequence = sequences.get(table)
        if sequence:
            sql.append(f"REVOKE ALL ON SEQUENCE {sequence} FROM {roles}")
            inserting = [role for role in APP_ROLES if "INSERT" in TABLE_ACCESS.get(table, {}).get(role, frozenset())]
            if inserting:
                sql.append(f"GRANT USAGE, SELECT ON SEQUENCE {sequence} TO {', '.join(inserting)}")
    return sql


def _resolve(connection) -> tuple[dict[str, str], str]:
    missing = [table for table in sorted(TABLE_ACCESS)
               if connection.execute(text("SELECT to_regclass(:name)"), {"name": f"{SCHEMA}.{table}"}).scalar() is None]
    if missing:
        raise SystemExit(f"tables missing from the database (run the migrations first): {', '.join(missing)}")
    sequences = {}
    for table in serial_tables():
        sequence = connection.execute(text("SELECT pg_get_serial_sequence(:table, 'id')"),
                                      {"table": f"{SCHEMA}.{table}"}).scalar()
        if sequence:
            sequences[table] = sequence
    return sequences, connection.execute(text("SELECT current_database()")).scalar()


def main(argv: list[str] | None = None, *, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="apply the privileges")
    mode.add_argument("--print-only", action="store_true", help="print the SQL without connecting")
    args = parser.parse_args(argv)

    if args.print_only:
        for statement in statements(conventional_sequences()):
            print(statement + ";", file=out)
        return 0

    from ..config import settings

    engine = create_engine(settings.database_url)
    if engine.dialect.name != "postgresql":
        parser.error("database privileges exist only on PostgreSQL")
    try:
        with engine.connect() as connection:
            sequences, database = _resolve(connection)
            sql = statements(sequences, database)
            if not args.apply:
                for statement in sql:
                    print(statement + ";", file=out)
                return 0  # closing the connection rolls back the read-only lookups
            for statement in sql:
                connection.execute(text(statement))
            connection.commit()
        print(f"applied {len(sql)} privilege statements", file=out)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
