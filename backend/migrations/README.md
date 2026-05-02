# SQL migrations (legacy)

New schema changes are managed by Alembic under `backend/alembic/`.
Keep this directory only for historical SQL migrations that have already been
converted to Alembic revisions.

- Do not add new `.sql` migrations here.
- Add new schema changes with `cd backend && alembic revision --autogenerate -m "<name>"`.
- Apply migrations with `cd backend && alembic upgrade head`.
- The former startup SQL runner has been superseded by Alembic.
