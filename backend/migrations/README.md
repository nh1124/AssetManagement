# SQL migrations

Place one migration per `.sql` file in this directory.

- Files are applied automatically at backend startup, in filename order.
- Applied files are recorded in the `schema_migrations` table and are not run again.
- Do not edit a migration after it has been applied. Add a new file instead.
- Use an ordered filename such as `20260502_001_add_example_column.sql`.
- To keep a draft in this directory without applying it, put `-- migration: skip` on the first non-empty line.

Keep migrations idempotent when practical, for example with `IF EXISTS` / `IF NOT EXISTS`.
