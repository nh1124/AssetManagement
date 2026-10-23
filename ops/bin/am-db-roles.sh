#!/bin/bash
# Create (or re-password) the three database roles and hand every table to am_owner (WP32 W5).
#
#   am-db-roles.sh            dry run: print the SQL with the passwords masked
#   am-db-roles.sh --apply    run it in one transaction
#
# Roles: am_owner (owns the tables; only the migrate service connects as it),
# am_user_app (user backend), am_admin_app (admin backend and CLI). Their
# privileges live in backend/app/db_access.py and are applied by the migrate
# service on every `docker compose up` (app.maintenance.db_grants).
#
# Passwords come from the repository's .env: AM_DB_OWNER_PASSWORD,
# AM_DB_USER_APP_PASSWORD, AM_DB_ADMIN_APP_PASSWORD (letters and digits only,
# at least 32 characters; `openssl rand -hex 32`). They reach psql on stdin as
# psql variables, never on a command line. Running --apply again after changing
# them rotates the passwords; restart migrate, backend and admin afterwards.
#
# psql runs inside the database container over its local socket as postgres,
# like the backup jobs, so no superuser password is needed here.

AM_JOB=db-roles
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"

: "${AM_REPO_DIR:=$HOME/AssetManagement}"
apply=0
case "${1:-}" in
  --apply) apply=1 ;;
  "") ;;
  *) echo "usage: am-db-roles.sh [--apply]" >&2; exit 64 ;;
esac

envfile="$AM_REPO_DIR/.env"
[ -f "$envfile" ] || { echo "missing $envfile" >&2; exit 1; }

env_value() {
  # The last KEY=VALUE line, without sourcing the file; surrounding quotes removed.
  sed -n "s/^$1=//p" "$envfile" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

owner_pw="$(env_value AM_DB_OWNER_PASSWORD)"
user_pw="$(env_value AM_DB_USER_APP_PASSWORD)"
admin_pw="$(env_value AM_DB_ADMIN_APP_PASSWORD)"
for name in owner_pw user_pw admin_pw; do
  value="${!name}"
  if [ -z "$value" ]; then echo "a database role password is missing from .env ($name)" >&2; exit 1; fi
  if [ "${#value}" -lt 32 ]; then echo "$name is shorter than 32 characters" >&2; exit 1; fi
  case "$value" in *[!A-Za-z0-9]*) echo "$name must contain only letters and digits (it goes into a URL)" >&2; exit 1 ;; esac
done
if [ "$owner_pw" = "$user_pw" ] || [ "$owner_pw" = "$admin_pw" ] || [ "$user_pw" = "$admin_pw" ]; then
  echo "the three role passwords must differ" >&2; exit 1
fi

sql() {
  cat <<SQL
\\set ON_ERROR_STOP 1
BEGIN;
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION', role)
  FROM unnest(ARRAY['am_owner', 'am_user_app', 'am_admin_app']) AS role
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role) \\gexec
ALTER ROLE am_owner PASSWORD :'owner_pw';
ALTER ROLE am_user_app PASSWORD :'user_pw';
ALTER ROLE am_admin_app PASSWORD :'admin_pw';
GRANT CONNECT ON DATABASE "$AM_DB_NAME" TO am_owner, am_user_app, am_admin_app;
GRANT USAGE, CREATE ON SCHEMA public TO am_owner;
GRANT USAGE ON SCHEMA public TO am_user_app, am_admin_app;
-- Tables (their serial sequences follow them), views, free-standing sequences and enum/domain types.
SELECT format('ALTER TABLE %I.%I OWNER TO am_owner', schemaname, tablename)
  FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'am_owner' \\gexec
SELECT format('ALTER VIEW %I.%I OWNER TO am_owner', schemaname, viewname)
  FROM pg_views WHERE schemaname = 'public' AND viewowner <> 'am_owner' \\gexec
SELECT format('ALTER SEQUENCE %I.%I OWNER TO am_owner', n.nspname, c.relname)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind = 'S' AND n.nspname = 'public' AND pg_get_userbyid(c.relowner) <> 'am_owner'
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i')) \\gexec
SELECT format('ALTER TYPE %I.%I OWNER TO am_owner', n.nspname, t.typname)
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd') AND pg_get_userbyid(t.typowner) <> 'am_owner' \\gexec
COMMIT;
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname LIKE 'am\\_%' ORDER BY rolname;
SELECT tableowner, count(*) AS tables FROM pg_tables WHERE schemaname = 'public' GROUP BY tableowner;
SQL
}

if [ "$apply" -ne 1 ]; then
  echo "-- dry run: would run, as postgres in $AM_DB_CONTAINER on database $AM_DB_NAME:"
  echo "\\set owner_pw '********'"
  echo "\\set user_pw '********'"
  echo "\\set admin_pw '********'"
  sql
  echo "-- then: the migrate service applies the privileges (app.maintenance.db_grants) on the next 'docker compose up'."
  exit 0
fi

{
  printf "\\\\set owner_pw '%s'\n\\\\set user_pw '%s'\n\\\\set admin_pw '%s'\n" "$owner_pw" "$user_pw" "$admin_pw"
  sql
} | docker exec -i "$AM_DB_CONTAINER" psql -U "$AM_DB_USER" -d "$AM_DB_NAME" -v ON_ERROR_STOP=1 -q
echo "roles ready; run 'docker compose up -d' so the migrate service applies the privileges"
