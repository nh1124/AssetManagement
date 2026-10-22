#!/bin/bash
# Shared helpers for the ops jobs (backup, restore-verify, log archive, watchdog).
#
# Every job writes two things besides its real output:
#   - one JSON line per event to $AM_OPS_LOG (start / step / end / error), and
#   - a status file $AM_STATE_DIR/status/<job>.json describing the last run.
# The status files are the contract a future admin screen reads; nothing else
# should need to parse the log to know whether a job is healthy.

set -euo pipefail

AM_OPS_CONFIG="${AM_OPS_CONFIG:-$HOME/.config/am-ops/config.env}"
if [ -f "$AM_OPS_CONFIG" ]; then
  # shellcheck disable=SC1090
  . "$AM_OPS_CONFIG"
fi

: "${AM_DB_CONTAINER:=finance-db}"
: "${AM_DB_NAME:=finance_ide}"
: "${AM_DB_USER:=postgres}"
: "${AM_CONTAINERS:=finance-db finance-backend finance-frontend finance-mcp finance-admin}"
# Optional single VPN address permitted for the admin port by am-status.
: "${AM_ADMIN_ALLOWED_BIND:=}"
: "${AM_BACKUP_ROOT:=$HOME/backups/assetmanagement}"
: "${AM_STATE_DIR:=$HOME/.local/state/am-ops}"
: "${AM_OPS_LOG:=$AM_STATE_DIR/ops.log}"
# Space-separated extra directories that receive a copy of every artifact.
: "${AM_MIRROR_DIRS:=}"
# When set, copies written to mirrors are gpg-encrypted with this passphrase
# file. The primary copy under AM_BACKUP_ROOT stays plain so a restore never
# depends on the key.
: "${AM_GPG_PASSPHRASE_FILE:=}"
: "${AM_RETAIN_HOURLY:=48}"
: "${AM_RETAIN_DAILY:=14}"
: "${AM_RETAIN_WEEKLY:=8}"
: "${AM_RETAIN_MONTHLY:=12}"
: "${AM_LOG_RETAIN_DAYS:=400}"
# When a container's forward log read stops short (a damaged json-file log),
# am-logs-archive reads backwards with `--tail`, starting at this many lines and
# doubling up to the maximum until it reaches the cursor.
: "${AM_LOG_TAIL_START:=1000}"
: "${AM_LOG_TAIL_MAX:=200000}"
# Dead-man's-switch URLs, pinged only on success. Empty disables.
: "${AM_HEARTBEAT_URL_BACKUP:=}"
: "${AM_HEARTBEAT_URL_WATCHDOG:=}"
# End-to-end probe the watchdog runs through nginx. Empty disables.
: "${AM_PROBE_URL:=http://127.0.0.1:15173/api/health}"
: "${AM_WD_AUTO_RESTART:=1}"
: "${AM_WD_UNHEALTHY_THRESHOLD:=3}"
: "${AM_WD_RESTART_COOLDOWN_SEC:=600}"
: "${AM_WD_MAX_RESTARTS_PER_HOUR:=3}"
# 0: a stopped ("exited") container is reported, not started. See am-watchdog.sh.
: "${AM_WD_START_STOPPED:=0}"
: "${AM_DISK_WARN_PERCENT:=90}"

mkdir -p "$AM_STATE_DIR/status" "$AM_BACKUP_ROOT"
chmod 700 "$AM_STATE_DIR" "$AM_BACKUP_ROOT" 2>/dev/null || true

AM_RUN_ID="${AM_RUN_ID:-$(date +%Y%m%dT%H%M%S)-$$}"
AM_JOB="${AM_JOB:-ops}"

# log_event LEVEL EVENT [key=value ...]
log_event() {
  local level="$1" event="$2"
  shift 2
  AM_LOG_LEVEL="$level" AM_LOG_EVENT="$event" AM_JOB="$AM_JOB" AM_RUN_ID="$AM_RUN_ID" \
    python3 - "$@" <<'PY' | tee -a "$AM_OPS_LOG" >&2
import json, os, socket, sys
from datetime import datetime, timezone

record = {
    "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
    "level": os.environ["AM_LOG_LEVEL"],
    "component": "ops",
    "job": os.environ["AM_JOB"],
    "event": os.environ["AM_LOG_EVENT"],
    "run_id": os.environ["AM_RUN_ID"],
    "host": socket.gethostname(),
}
for pair in sys.argv[1:]:
    key, _, value = pair.partition("=")
    if value.lstrip("-").isdigit():
        record[key] = int(value)
    else:
        record[key] = value
print(json.dumps(record, ensure_ascii=False))
PY
}

# write_status JOB key=value ...   (values are stored as strings or ints)
write_status() {
  local job="$1"
  shift
  local target="$AM_STATE_DIR/status/$job.json"
  AM_RUN_ID="$AM_RUN_ID" python3 - "$target" "$@" <<'PY'
import json, os, sys
from datetime import datetime, timezone

target = sys.argv[1]
try:
    with open(target, encoding="utf-8") as handle:
        status = json.load(handle)
except (OSError, ValueError):
    status = {}
status["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
status["run_id"] = os.environ["AM_RUN_ID"]
for pair in sys.argv[2:]:
    key, _, value = pair.partition("=")
    status[key] = int(value) if value.lstrip("-").isdigit() else value
tmp = target + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(status, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(tmp, target)
PY
}

heartbeat() {
  local url="$1"
  [ -n "$url" ] || return 0
  curl -fsS -m 10 --retry 2 -o /dev/null "$url" || log_event warn heartbeat_failed
}

require_docker() {
  if ! docker info >/dev/null 2>&1; then
    log_event error docker_unreachable
    return 1
  fi
}

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || echo false)" = "true" ]
}

# One job instance at a time; a slow run must not overlap the next timer tick.
single_instance() {
  local lock="$AM_STATE_DIR/$AM_JOB.lock"
  exec 9>"$lock"
  if ! flock -n 9; then
    log_event warn already_running
    exit 0
  fi
}

# copy_artifact SRC DEST_DIR  -> plain copy, or gpg when a passphrase is set.
copy_to_mirror() {
  local src="$1" dest_dir="$2"
  mkdir -p "$dest_dir"
  if [ -n "$AM_GPG_PASSPHRASE_FILE" ]; then
    gpg --batch --yes --quiet --symmetric --cipher-algo AES256 \
      --passphrase-file "$AM_GPG_PASSPHRASE_FILE" \
      --output "$dest_dir/$(basename "$src").gpg" "$src"
  else
    cp -f "$src" "$dest_dir/"
  fi
}

# prune_keep DIR GLOB KEEP  -> delete all but the newest KEEP matches (by name;
# artifact names sort chronologically).
prune_keep() {
  local dir="$1" glob="$2" keep="$3"
  [ -d "$dir" ] || return 0
  # shellcheck disable=SC2012
  ls -1 "$dir"/$glob 2>/dev/null | sort -r | tail -n +"$((keep + 1))" | while read -r old; do
    rm -f -- "$old"
  done
}
