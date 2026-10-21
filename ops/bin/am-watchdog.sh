#!/bin/bash
# Notice when the stack is down and try the one safe repair: restart.
#
# Docker's restart policy already brings back a container that exits. It does
# nothing for a container that is running but unhealthy, so that case is
# handled here: after AM_WD_UNHEALTHY_THRESHOLD consecutive bad checks the
# container is restarted, at most AM_WD_MAX_RESTARTS_PER_HOUR times with
# AM_WD_RESTART_COOLDOWN_SEC between attempts. Past that the watchdog stops
# and reports, because a container that will not stay up needs a person.
#
# It never runs `docker compose up`: recreating from the working tree could
# start code or migrations that are still being edited.
#
# It does not start a stopped container either. With `restart: unless-stopped`
# Docker itself restarts anything that crashed, so a container that stays
# "exited" was stopped by a person, and starting it again would undo that.
# AM_WD_START_STOPPED=1 changes this for a host where nobody stops things by
# hand. To pause all recovery during maintenance:
#     touch ~/.local/state/am-ops/maintenance      (remove it afterwards)

AM_JOB=watchdog
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"
single_instance

state="$AM_STATE_DIR/watchdog"
mkdir -p "$state"
now=$(date +%s)
overall=ok
detail=""

note() { overall="$1"; detail="${detail:+$detail,}$2"; }

if ! docker info >/dev/null 2>&1; then
  # Only log the transition; a stopped Docker Desktop would otherwise write a
  # line every minute.
  if [ ! -e "$state/docker-down" ]; then
    log_event error docker_unreachable
    : >"$state/docker-down"
  fi
  write_status watchdog overall=down detail=docker_unreachable checked_at="$(date -Iseconds)"
  exit 1
fi
if [ -e "$state/docker-down" ]; then
  rm -f "$state/docker-down"
  log_event info docker_reachable_again
fi

restarts_last_hour() {
  local file="$state/$1.restarts" count=0 ts
  [ -f "$file" ] || { echo 0; return; }
  while read -r ts; do
    [ $((now - ts)) -lt 3600 ] && count=$((count + 1))
  done <"$file"
  echo "$count"
}

try_restart() {
  local container="$1" action="$2" last=0 recent
  [ "$AM_WD_AUTO_RESTART" = "1" ] || return 0
  [ ! -e "$AM_STATE_DIR/maintenance" ] || return 0
  [ -f "$state/$container.last-restart" ] && last=$(cat "$state/$container.last-restart")
  recent=$(restarts_last_hour "$container")
  if [ "$recent" -ge "$AM_WD_MAX_RESTARTS_PER_HOUR" ]; then
    if [ ! -e "$state/$container.gave-up" ]; then
      log_event error giving_up container="$container" restarts_last_hour="$recent"
      : >"$state/$container.gave-up"
    fi
    return
  fi
  [ $((now - last)) -ge "$AM_WD_RESTART_COOLDOWN_SEC" ] || return 0
  log_event warn recovering container="$container" action="$action"
  if docker "$action" "$container" >/dev/null 2>&1; then
    echo "$now" >"$state/$container.last-restart"
    echo "$now" >>"$state/$container.restarts"
    tail -n 20 "$state/$container.restarts" >"$state/$container.restarts.tmp"
    mv "$state/$container.restarts.tmp" "$state/$container.restarts"
    echo 0 >"$state/$container.bad"
  else
    log_event error recovery_failed container="$container" action="$action"
  fi
}

for container in $AM_CONTAINERS; do
  status=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo missing)
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || echo missing)
  bad=0
  [ -f "$state/$container.bad" ] && bad=$(cat "$state/$container.bad")

  if [ "$status" = "missing" ]; then
    note down "$container:missing"
    [ "$bad" -gt 0 ] || log_event error container_missing container="$container"
    echo $((bad + 1)) >"$state/$container.bad"
  elif [ "$status" != "running" ]; then
    note down "$container:$status"
    [ "$bad" -gt 0 ] || log_event warn container_not_running container="$container" status="$status"
    echo $((bad + 1)) >"$state/$container.bad"
    # "restarting" is Docker already at work; "exited" is a manual stop
    # unless this host opted in to starting those.
    if [ "$status" = "exited" ] && [ "$AM_WD_START_STOPPED" = "1" ]; then
      try_restart "$container" start
    fi
  elif [ "$health" = "unhealthy" ]; then
    bad=$((bad + 1))
    echo "$bad" >"$state/$container.bad"
    note degraded "$container:unhealthy"
    [ "$bad" -lt "$AM_WD_UNHEALTHY_THRESHOLD" ] || try_restart "$container" restart
  else
    if [ "$bad" -gt 0 ]; then
      log_event info recovered container="$container" after_bad_checks="$bad"
      rm -f "$state/$container.gave-up"
    fi
    echo 0 >"$state/$container.bad"
  fi
done

if [ -n "$AM_PROBE_URL" ] && [ "$overall" = "ok" ]; then
  if ! curl -fsS -m 5 -o /dev/null "$AM_PROBE_URL"; then
    probe_bad=0
    [ -f "$state/probe.bad" ] && probe_bad=$(cat "$state/probe.bad")
    echo $((probe_bad + 1)) >"$state/probe.bad"
    note degraded probe_failed
    [ "$probe_bad" -ne 2 ] || log_event warn probe_failing url="$AM_PROBE_URL"
  else
    echo 0 >"$state/probe.bad"
  fi
fi

disk=$(df --output=pcent "$AM_BACKUP_ROOT" | tail -n 1 | tr -dc '0-9')
if [ "${disk:-0}" -ge "$AM_DISK_WARN_PERCENT" ]; then
  note degraded "disk:${disk}%"
  [ -e "$state/disk-warned" ] || { log_event warn disk_filling used_percent="$disk"; : >"$state/disk-warned"; }
else
  rm -f "$state/disk-warned"
fi

# A backup that has stopped arriving is an outage too, just a quiet one.
backup_age=-1
last_backup=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("last_success_at",""))' \
  "$AM_STATE_DIR/status/backup.json" 2>/dev/null || true)
if [ -n "$last_backup" ]; then
  backup_age=$(( now - $(date -d "$last_backup" +%s) ))
  if [ "$backup_age" -gt 10800 ]; then
    note degraded backup_stale
    [ -e "$state/backup-stale" ] || { log_event warn backup_stale age_sec="$backup_age"; : >"$state/backup-stale"; }
  else
    rm -f "$state/backup-stale"
  fi
fi

[ ! -e "$AM_STATE_DIR/maintenance" ] || detail="${detail:+$detail,}maintenance"

previous=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("overall",""))' \
  "$AM_STATE_DIR/status/watchdog.json" 2>/dev/null || true)
write_status watchdog overall="$overall" detail="$detail" checked_at="$(date -Iseconds)" \
  disk_used_percent="${disk:-0}" backup_age_sec="$backup_age"
if [ "$previous" != "$overall" ]; then
  log_event "$([ "$overall" = ok ] && echo info || echo warn)" state_changed from="${previous:-unknown}" to="$overall" detail="$detail"
fi

[ "$overall" = "ok" ] && heartbeat "$AM_HEARTBEAT_URL_WATCHDOG"
exit 0
