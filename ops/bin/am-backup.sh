#!/bin/bash
# Snapshot the database: pg_dump (custom format) + roles + a manifest.
#
# Layout under AM_BACKUP_ROOT and under every mirror:
#   db/hourly/  db/daily/  db/weekly/  db/monthly/
# A run always writes to hourly/. The first run of a day, ISO week and month
# is also kept in the matching tier, so retention is a count per tier.
#
# The dump is checked with pg_restore --list before it is accepted; a file the
# archive reader cannot open never replaces a good one.

AM_JOB=backup
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"
single_instance

started=$(date +%s)
stamp=$(date +%Y%m%dT%H%M%S)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fail() {
  log_event error end reason="$1"
  write_status backup last_result=failed last_error="$1" last_failure_at="$(date -Iseconds)"
  exit 1
}

log_event info start container="$AM_DB_CONTAINER" database="$AM_DB_NAME"
require_docker || fail docker_unreachable
container_running "$AM_DB_CONTAINER" || fail db_container_not_running

base="${AM_DB_NAME}_${stamp}"
dump="$work/$base.dump"
globals="$work/$base.globals.sql"
manifest="$work/$base.manifest.json"

docker exec "$AM_DB_CONTAINER" pg_dump -U "$AM_DB_USER" -d "$AM_DB_NAME" -Fc >"$dump" \
  || fail pg_dump_failed
docker exec "$AM_DB_CONTAINER" pg_dumpall -U "$AM_DB_USER" --globals-only >"$globals" \
  || fail pg_dumpall_failed
docker exec -i "$AM_DB_CONTAINER" pg_restore --list <"$dump" >/dev/null \
  || fail dump_unreadable

size=$(stat -c %s "$dump")
[ "$size" -gt 1024 ] || fail dump_too_small
sha=$(sha256sum "$dump" | cut -d' ' -f1)

# Row counts and the ledger invariant go in the manifest so a restore can be
# compared against what the source database held at dump time.
counts=$(docker exec -i "$AM_DB_CONTAINER" psql -U "$AM_DB_USER" -d "$AM_DB_NAME" -At -v ON_ERROR_STOP=1 <<'SQL'
select json_build_object(
  'alembic_revision', (select version_num from alembic_version limit 1),
  'clients', (select count(*) from clients),
  'accounts', (select count(*) from accounts),
  'transactions', (select count(*) from transactions),
  'journal_entries', (select count(*) from journal_entries),
  'journal_debit_minor_total', (select coalesce(sum(debit_minor), 0) from journal_entries),
  'journal_credit_minor_total', (select coalesce(sum(credit_minor), 0) from journal_entries),
  'tables', (select count(*) from information_schema.tables where table_schema = 'public'),
  'server_version', current_setting('server_version')
);
SQL
) || fail manifest_query_failed

AM_M_FILE="$base.dump" AM_M_SHA="$sha" AM_M_SIZE="$size" AM_M_COUNTS="$counts" \
  python3 - "$manifest" <<'PY'
import json, os, socket, sys
from datetime import datetime, timezone

manifest = {
    "format": "am-ops-backup/1",
    "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "host": socket.gethostname(),
    "file": os.environ["AM_M_FILE"],
    "sha256": os.environ["AM_M_SHA"],
    "size_bytes": int(os.environ["AM_M_SIZE"]),
    "database": json.loads(os.environ["AM_M_COUNTS"]),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

chmod 600 "$dump" "$globals" "$manifest"

day=$(date +%Y%m%d)
week=$(date +%GW%V)
month=$(date +%Y%m)

# place ROOT COPY_FN: write the three files into hourly/ and promote to the
# slower tiers when this is the first artifact of the period.
place() {
  local root="$1" copy="$2"
  local tier marker
  for tier in hourly daily weekly monthly; do
    mkdir -p "$root/db/$tier" || return 1
  done
  # Explicit returns: this function is called inside `if`, where `set -e`
  # does not apply, and a half-written mirror must not be reported as good.
  "$copy" "$dump" "$root/db/hourly" || return 1
  "$copy" "$globals" "$root/db/hourly" || return 1
  "$copy" "$manifest" "$root/db/hourly" || return 1
  for tier in daily weekly monthly; do
    case "$tier" in
      daily) marker="$day" ;;
      weekly) marker="$week" ;;
      monthly) marker="$month" ;;
    esac
    if [ ! -e "$root/db/$tier/.period-$marker" ]; then
      "$copy" "$dump" "$root/db/$tier" || return 1
      "$copy" "$globals" "$root/db/$tier" || return 1
      "$copy" "$manifest" "$root/db/$tier" || return 1
      rm -f "$root/db/$tier"/.period-*
      : >"$root/db/$tier/.period-$marker"
    fi
  done
  # Three files per snapshot, so the glob is per extension.
  local ext
  for ext in 'dump*' 'globals.sql*' 'manifest.json*'; do
    prune_keep "$root/db/hourly" "${AM_DB_NAME}_*.$ext" "$AM_RETAIN_HOURLY"
    prune_keep "$root/db/daily" "${AM_DB_NAME}_*.$ext" "$AM_RETAIN_DAILY"
    prune_keep "$root/db/weekly" "${AM_DB_NAME}_*.$ext" "$AM_RETAIN_WEEKLY"
    prune_keep "$root/db/monthly" "${AM_DB_NAME}_*.$ext" "$AM_RETAIN_MONTHLY"
  done
}

plain_copy() { cp -f "$1" "$2/"; chmod 600 "$2/$(basename "$1")" 2>/dev/null || true; }

place "$AM_BACKUP_ROOT" plain_copy
log_event info stored root="$AM_BACKUP_ROOT" file="$base.dump" size_bytes="$size" sha256="$sha"

mirrors_ok=0
mirrors_failed=0
for mirror in $AM_MIRROR_DIRS; do
  if place "$mirror" copy_to_mirror 2>>"$AM_OPS_LOG"; then
    mirrors_ok=$((mirrors_ok + 1))
    log_event info mirrored root="$mirror" encrypted="$([ -n "$AM_GPG_PASSPHRASE_FILE" ] && echo yes || echo no)"
  else
    mirrors_failed=$((mirrors_failed + 1))
    log_event error mirror_failed root="$mirror"
  fi
done

elapsed=$(( $(date +%s) - started ))
write_status backup last_result=ok last_success_at="$(date -Iseconds)" last_file="$base.dump" \
  last_sha256="$sha" last_size_bytes="$size" mirrors_ok="$mirrors_ok" \
  mirrors_failed="$mirrors_failed" last_duration_sec="$elapsed" last_error=""
log_event info end result=ok duration_sec="$elapsed" mirrors_ok="$mirrors_ok" mirrors_failed="$mirrors_failed"

# A mirror failure is reported but does not fail the job: the primary copy is
# good, and the dead-man's switch should keep seeing a run.
heartbeat "$AM_HEARTBEAT_URL_BACKUP"
[ "$mirrors_failed" -eq 0 ] || exit 2
