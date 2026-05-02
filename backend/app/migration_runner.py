from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


MIGRATIONS_TABLE = "schema_migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@dataclass(frozen=True)
class MigrationFile:
    version: str
    path: Path
    checksum: str
    sql: str


def _checksum(contents: str) -> str:
    return hashlib.sha256(contents.encode("utf-8")).hexdigest()


def _is_skipped(contents: str) -> bool:
    for line in contents.splitlines():
        stripped = line.strip().lower()
        if not stripped:
            continue
        return stripped.startswith("-- migration: skip") or "(unused" in stripped
    return True


def _load_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[MigrationFile]:
    if not migrations_dir.exists():
        return []

    migrations: list[MigrationFile] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        contents = path.read_text(encoding="utf-8-sig")
        if _is_skipped(contents):
            print(f"Skipping migration {path.name}")
            continue
        migrations.append(
            MigrationFile(
                version=path.stem,
                path=path,
                checksum=_checksum(contents),
                sql=contents.strip(),
            )
        )
    return migrations


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    i = 0
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_quote_tag: str | None = None

    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""

        if in_line_comment:
            current.append(char)
            if char == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            current.append(char)
            if char == "*" and next_char == "/":
                current.append(next_char)
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if dollar_quote_tag:
            if sql.startswith(dollar_quote_tag, i):
                current.append(dollar_quote_tag)
                i += len(dollar_quote_tag)
                dollar_quote_tag = None
            else:
                current.append(char)
                i += 1
            continue

        if in_single_quote:
            current.append(char)
            if char == "'" and next_char == "'":
                current.append(next_char)
                i += 2
                continue
            if char == "'":
                in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            current.append(char)
            if char == '"':
                in_double_quote = False
            i += 1
            continue

        if char == "-" and next_char == "-":
            current.extend([char, next_char])
            in_line_comment = True
            i += 2
            continue

        if char == "/" and next_char == "*":
            current.extend([char, next_char])
            in_block_comment = True
            i += 2
            continue

        if char == "'":
            current.append(char)
            in_single_quote = True
            i += 1
            continue

        if char == '"':
            current.append(char)
            in_double_quote = True
            i += 1
            continue

        if char == "$":
            tag_end = sql.find("$", i + 1)
            if tag_end != -1:
                tag = sql[i : tag_end + 1]
                tag_body = tag[1:-1]
                if tag == "$$" or tag_body.replace("_", "").isalnum():
                    current.append(tag)
                    dollar_quote_tag = tag
                    i = tag_end + 1
                    continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def run_migrations(engine: Engine, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    """Apply backend/migrations/*.sql exactly once, in filename order."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
                    version VARCHAR(255) PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    checksum VARCHAR(64) NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        applied_rows = conn.execute(
            text(f"SELECT version, checksum FROM {MIGRATIONS_TABLE}")
        ).all()
        applied = {row.version: row.checksum for row in applied_rows}

        for migration in _load_migrations(migrations_dir):
            previous_checksum = applied.get(migration.version)
            if previous_checksum:
                if previous_checksum != migration.checksum:
                    raise RuntimeError(
                        f"Migration {migration.path.name} was already applied with a different checksum. "
                        "Create a new migration file instead of editing applied migrations."
                    )
                continue

            if not migration.sql:
                continue

            print(f"Applying migration {migration.path.name}")
            for statement in _split_sql_statements(migration.sql):
                conn.exec_driver_sql(statement)
            conn.execute(
                text(
                    f"""
                    INSERT INTO {MIGRATIONS_TABLE} (version, filename, checksum)
                    VALUES (:version, :filename, :checksum)
                    """
                ),
                {
                    "version": migration.version,
                    "filename": migration.path.name,
                    "checksum": migration.checksum,
                },
            )
