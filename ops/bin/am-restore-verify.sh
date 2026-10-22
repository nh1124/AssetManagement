#!/bin/bash
# Prove that a backup can be restored: load it into a throwaway PostgreSQL
# container and compare what comes out with the manifest written at dump time.
#
# Usage: am-restore-verify.sh [path/to/file.dump]   (default: newest hourly)
#
# Only a dump taken at the live database's alembic revision is verified. One
# from an older schema is recorded as skipped: the checks below are written for
# the current tables, and restoring it says nothing about today's backups.
#
# The scratch container has no published ports and no volume; it never touches
# the live database.

AM_JOB=restore-verify
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"
single_instance

dump="${1:-}"
if [ -z "$dump" ]; then
  # shellcheck disable=SC2012
  dump=$(ls -1 "$AM_BACKUP_ROOT"/db/hourly/"${AM_DB_NAME}"_*.dump 2>/dev/null | sort | tail -n 1 || true)
fi

fail() {
  log_event error end reason="$1"
  write_status restore-verify last_result=failed last_error="$1" last_failure_at="$(date -Iseconds)"
  exit 1
}

log_event info start file="${dump:-none}"
[ -n "$dump" ] && [ -f "$dump" ] || fail no_dump_found
manifest="${dump%.dump}.manifest.json"
[ -f "$manifest" ] || fail manifest_missing
require_docker || fail docker_unreachable

expected_sha=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$manifest")
actual_sha=$(sha256sum "$dump" | cut -d' ' -f1)
[ "$expected_sha" = "$actual_sha" ] || fail checksum_mismatch

dump_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("database", {}).get("alembic_revision") or "")' "$manifest")
current_revision=$(docker exec "$AM_DB_CONTAINER" psql -U "$AM_DB_USER" -d "$AM_DB_NAME" -At -v ON_ERROR_STOP=1 \
  -c 'select version_num from alembic_version limit 1' 2>/dev/null) || fail current_revision_unreadable
[ -n "$current_revision" ] || fail current_revision_unreadable
if [ "$dump_revision" != "$current_revision" ]; then
  write_status restore-verify last_result=skipped last_skipped_at="$(date -Iseconds)" \
    last_file="$(basename "$dump")" skip_reason=schema_not_current \
    dump_revision="${dump_revision:-unknown}" current_revision="$current_revision" last_error=""
  log_event info end result=skipped reason=schema_not_current file="$(basename "$dump")" \
    dump_revision="${dump_revision:-unknown}" current_revision="$current_revision"
  exit 0
fi

image=$(docker inspect -f '{{.Config.Image}}' "$AM_DB_CONTAINER" 2>/dev/null || echo postgres:16-alpine)
scratch="am-restore-verify-$$"
cleanup() { docker rm -f "$scratch" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$scratch" --network none --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD="$(head -c 18 /dev/urandom | base64)" "$image" >/dev/null \
  || fail scratch_start_failed

ready=0
for _ in $(seq 1 60); do
  # The image restarts postgres once during init; require the final server.
  if docker exec "$scratch" sh -c 'pg_isready -U postgres -q && [ -S /var/run/postgresql/.s.PGSQL.5432 ]' 2>/dev/null \
     && docker logs "$scratch" 2>&1 | grep -q 'PostgreSQL init process complete'; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || fail scratch_not_ready
sleep 1

docker exec "$scratch" createdb -U postgres "$AM_DB_NAME" || fail createdb_failed
docker exec -i "$scratch" pg_restore -U postgres -d "$AM_DB_NAME" --no-owner --no-privileges --exit-on-error <"$dump" \
  || fail pg_restore_failed

restored=$(docker exec -i "$scratch" psql -U postgres -d "$AM_DB_NAME" -At -v ON_ERROR_STOP=1 <<'SQL'
select json_build_object(
  'alembic_revision', (select version_num from alembic_version limit 1),
  'clients', (select count(*) from clients),
  'accounts', (select count(*) from accounts),
  'transactions', (select count(*) from transactions),
  'journal_entries', (select count(*) from journal_entries),
  'journal_debit_minor_total', (select coalesce(sum(debit_minor), 0) from journal_entries),
  'journal_credit_minor_total', (select coalesce(sum(credit_minor), 0) from journal_entries),
  'tables', (select count(*) from information_schema.tables where table_schema = 'public')
);
SQL
) || fail restored_query_failed

verdict=$(AM_RESTORED="$restored" python3 - "$manifest" <<'PY'
import json, os, sys

expected = json.load(open(sys.argv[1], encoding="utf-8"))["database"]
restored = json.loads(os.environ["AM_RESTORED"])
problems = [
    f"{key}:{expected.get(key)}!={value}"
    for key, value in restored.items()
    if expected.get(key) != value
]
if restored["journal_debit_minor_total"] != restored["journal_credit_minor_total"]:
    problems.append("journal_unbalanced")
print("ok" if not problems else ",".join(problems))
PY
)

[ "$verdict" = "ok" ] || fail "mismatch:$verdict"

write_status restore-verify last_result=ok last_success_at="$(date -Iseconds)" \
  last_file="$(basename "$dump")" last_error="" skip_reason="" \
  dump_revision="$dump_revision" current_revision="$current_revision"
log_event info end result=ok file="$(basename "$dump")"
