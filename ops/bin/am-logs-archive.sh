#!/bin/bash
# Copy container logs out of Docker before Docker can lose them.
#
# `docker logs` only keeps what the current container instance wrote: a
# recreate (every `docker compose up` after a config change) drops the history.
# Each run appends the lines written since the previous run to
#   AM_BACKUP_ROOT/logs/<container>/<YYYY-MM-DD>.log
# compresses closed days, and mirrors them like the database snapshots.
#
# A json-file log damaged mid-file (finance-backend after the unclean Docker
# Desktop stop on 2026-10-09) makes every forward read, `--since` included,
# stop at the damage with exit 0 and no error, while `--tail` still reads the
# part after it. So each run checks the forward read against the newest lines,
# and when it stopped short takes the rest from `--tail`, reports the container
# as stuck and the run as degraded instead of ok.

AM_JOB=logs-archive
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"
single_instance

require_docker || { write_status logs-archive last_result=failed last_error=docker_unreachable; exit 1; }

# `docker logs --timestamps` prints fixed-width UTC RFC 3339 with nanoseconds
# (2026-10-20T01:02:03.000000000Z), so timestamps order correctly as strings.
TS_MATCH='match($0, /^[0-9-]+T[0-9:.]+Z /) { ts = substr($0, 1, RLENGTH - 1)'

# newest_ts / oldest_ts [FILE]: latest / earliest timestamp ("" when none).
# Lines from stdout and stderr can be a few ms out of order, so these are not
# simply the last and first lines.
newest_ts() { LC_ALL=C awk "$TS_MATCH; if (ts > t) t = ts }"' END { print t }' "$@"; }
oldest_ts() { LC_ALL=C awk "$TS_MATCH; if (t == \"\" || ts < t) t = ts }"' END { print t }' "$@"; }

# ts_after A B: A is a timestamp later than B.
ts_after() { LC_ALL=C awk -v a="$1" -v b="$2" 'BEGIN { exit !(a != "" && a > b) }'; }

# The cursor has whole seconds; pad it so it compares with log timestamps.
nano_ts() { case "$1" in *.*) echo "$1" ;; *) echo "${1%Z}.000000000Z" ;; esac; }

# newest_until CONTAINER HI: newest timestamp at or before HI among the last
# lines of the log. A short --tail read starts at the end of the file, so it
# works even when a forward read cannot get there.
newest_until() {
  docker logs --timestamps --tail 100 "$1" 2>&1 \
    | LC_ALL=C awk -v hi="$2" "$TS_MATCH; if (ts <= hi && ts > t) t = ts }"' END { print t }'
}

# tail_read CONTAINER N LO HI RAW: `--tail N` into RAW, and the lines with
# LO < timestamp <= HI into RAW.window.
tail_read() {
  docker logs --timestamps --tail "$2" "$1" >"$5" 2>&1 || return 1
  LC_ALL=C awk -v lo="$3" -v hi="$4" "$TS_MATCH; if (ts > lo && ts <= hi) print }" "$5" >"$5.window"
}

# tail_window CONTAINER LO HI OUT: the lines with LO < timestamp <= HI, read
# from the end of the log with --tail, doubling N until the read reaches back
# to LO. Sets tail_from (oldest timestamp reached) and tail_stop: covered,
# start (the whole log was read), damaged (the read reached the damaged spot)
# or max (AM_LOG_TAIL_MAX lines were not enough).
tail_window() {
  local container="$1" lo="$2" hi="$3" out="$4"
  local n="$AM_LOG_TAIL_START" good=0 bad best=-1 got mid raw
  raw=$(mktemp)
  tail_from="" tail_stop=""
  : >"$out"
  while :; do
    tail_read "$container" "$n" "$lo" "$hi" "$raw" || { rm -f "$raw" "$raw.window"; return 1; }
    got=$(wc -l <"$raw.window")
    if [ "$got" -lt "$best" ]; then
      # Longer than the part after the damage: the read started inside it and
      # returned less. Bisect for the longest read that still returns every
      # line it asked for, keeping that read's output.
      bad=$n
      while [ $((bad - good)) -gt 1 ]; do
        mid=$(((good + bad) / 2))
        docker logs --timestamps --tail "$mid" "$container" >"$raw" 2>&1 || break
        if [ "$(wc -l <"$raw")" -eq "$mid" ]; then
          good=$mid
          mv "$raw" "$raw.good"
        else
          bad=$mid
        fi
      done
      if [ -f "$raw.good" ]; then
        LC_ALL=C awk -v lo="$lo" -v hi="$hi" "$TS_MATCH; if (ts > lo && ts <= hi) print }" "$raw.good" >"$out"
        tail_from=$(oldest_ts "$raw.good")
      fi
      tail_stop=damaged
      break
    fi
    mv "$raw.window" "$out"
    best=$got good=$n tail_from=$(oldest_ts "$raw")
    if ! ts_after "$tail_from" "$lo"; then tail_stop=covered; break; fi
    if [ "$(wc -l <"$raw")" -lt "$n" ]; then tail_stop=start; break; fi
    if [ "$n" -ge "$AM_LOG_TAIL_MAX" ]; then tail_stop=max; break; fi
    n=$((n * 2))
    [ "$n" -le "$AM_LOG_TAIL_MAX" ] || n=$AM_LOG_TAIL_MAX
  done
  rm -f "$raw" "$raw.window" "$raw.good"
}

# report_stuck CONTAINER FORWARD_LINES TAIL_LINES: warn when a container's
# forward read starts failing and again once a day while it lasts, so a digest
# of any day's warnings shows it. The marker keeps the first sighting.
report_stuck() {
  local marker="$AM_STATE_DIR/logs-stuck.$1" first_seen="" warned_on=""
  if [ -f "$marker" ]; then read -r first_seen warned_on <"$marker" || true; fi
  [ -n "$first_seen" ] || first_seen=$(date -Iseconds)
  if [ "$warned_on" != "$today" ]; then
    # Costs one full forward read, which stops at the damage anyway.
    log_event warn forward_read_stuck container="$1" forward_lines="$2" tail_lines="$3" \
      forward_stops_at="$(docker logs --timestamps "$1" 2>&1 | newest_ts)" first_seen="$first_seen"
    warned_on=$today
  fi
  echo "$first_seen $warned_on" >"$marker"
}

until_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
hi=$(nano_ts "$until_ts")
today=$(date +%Y-%m-%d)
total=0
failed=0
stuck=""

for container in $AM_CONTAINERS; do
  cursor="$AM_STATE_DIR/logs-cursor.$container"
  since="1970-01-01T00:00:00Z"
  [ -f "$cursor" ] && since=$(cat "$cursor")
  dest="$AM_BACKUP_ROOT/logs/$container"
  mkdir -p "$dest"
  chunk=$(mktemp)
  read_ok=0
  if docker logs --timestamps --since "$since" --until "$until_ts" "$container" >"$chunk" 2>&1; then
    read_ok=1
    reached=$(newest_ts "$chunk")
    lo=${reached:-$(nano_ts "$since")}
    newest=$(newest_until "$container" "$hi") || newest=""
    if ts_after "$newest" "$lo"; then
      # The forward read stopped before lines that --tail can see.
      extra=$(mktemp)
      if tail_window "$container" "$lo" "$hi" "$extra"; then
        report_stuck "$container" "$(wc -l <"$chunk")" "$(wc -l <"$extra")"
        if [ "$tail_stop" = damaged ] || [ "$tail_stop" = max ]; then
          log_event warn logs_gap container="$container" after="$lo" before="$tail_from" reason="$tail_stop"
        fi
        cat "$extra" >>"$chunk"
        stuck="$stuck $container"
      else
        read_ok=0
      fi
      rm -f "$extra"
    elif [ -n "$reached" ] && [ -n "$newest" ] && [ -f "$AM_STATE_DIR/logs-stuck.$container" ]; then
      # Only when the forward read returned lines and agrees with the tail:
      # a quiet container proves nothing.
      rm -f "$AM_STATE_DIR/logs-stuck.$container"
      log_event info forward_read_recovered container="$container"
    fi
  fi
  if [ "$read_ok" -eq 1 ]; then
    lines=$(wc -l <"$chunk")
    if [ "$lines" -gt 0 ]; then
      cat "$chunk" >>"$dest/$today.log"
      chmod 600 "$dest/$today.log"
    fi
    echo "$until_ts" >"$cursor"
    total=$((total + lines))
  else
    # Nothing written and the cursor kept: the next run reads this window again.
    failed=$((failed + 1))
    log_event warn container_logs_unavailable container="$container"
  fi
  rm -f "$chunk"

  # The open day is mirrored on every run, so a lost machine costs at most
  # one interval of logs rather than a day.
  if [ -f "$dest/$today.log" ]; then
    for mirror in $AM_MIRROR_DIRS; do
      copy_to_mirror "$dest/$today.log" "$mirror/logs/$container" 2>>"$AM_OPS_LOG" \
        || log_event error mirror_failed root="$mirror" container="$container"
    done
  fi

  # Closed days are immutable: compress once, mirror the compressed file and
  # drop the uncompressed copy the mirror was holding.
  for old in "$dest"/*.log; do
    [ -e "$old" ] || continue
    [ "$(basename "$old")" = "$today.log" ] && continue
    gzip -f "$old"
    for mirror in $AM_MIRROR_DIRS; do
      if copy_to_mirror "$old.gz" "$mirror/logs/$container" 2>>"$AM_OPS_LOG"; then
        rm -f "$mirror/logs/$container/$(basename "$old")" "$mirror/logs/$container/$(basename "$old").gpg"
      else
        log_event error mirror_failed root="$mirror" container="$container"
      fi
    done
  done
  find "$dest" -name '*.log.gz' -mtime +"$AM_LOG_RETAIN_DAYS" -delete
done
stuck=${stuck# }

# The ops log itself is part of the record.
if [ -f "$AM_OPS_LOG" ]; then
  mkdir -p "$AM_BACKUP_ROOT/logs/ops"
  cp -f "$AM_OPS_LOG" "$AM_BACKUP_ROOT/logs/ops/ops.log"
fi

if [ "$failed" -gt 0 ]; then
  result=partial
elif [ -n "$stuck" ]; then
  result=degraded
else
  result=ok
fi
write_status logs-archive last_result="$result" \
  last_success_at="$(date -Iseconds)" last_lines="$total" containers_failed="$failed" \
  containers_stuck="$stuck"
summary=(lines="$total" containers_failed="$failed")
[ -z "$stuck" ] || summary+=(containers_stuck="$stuck")
[ "$total" -eq 0 ] || log_event info archived "${summary[@]}"
