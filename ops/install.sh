#!/bin/bash
# Install the ops jobs for the current user. Safe to run again after an update.
#
#   ops/install.sh                  install / update
#   ops/install.sh --set-repo-dir   also point AM_REPO_DIR at this checkout when
#                                   the config already names another one
#
# The scripts are copied out of the repository on purpose: the timers must
# keep working while the working tree is mid-edit, on another branch, or gone.
#
#   scripts  -> ~/.local/lib/am-ops/
#   config   -> ~/.config/am-ops/config.env   (created once, never overwritten,
#               except for AM_REPO_DIR below)
#   timers   -> ~/.config/systemd/user/am-*.{service,timer}
#   am-admin -> ~/.local/bin/am-admin (a link to the installed wrapper)
#
# AM_REPO_DIR (where am-admin, am-db-roles and am-rotate-secrets find .env and
# docker-compose.yml) is recorded from the checkout this script runs from, so a
# clone anywhere works on a new machine. It is not recorded from a linked git
# worktree (a branch being worked on is not the deployment), and an existing
# value that names another checkout is kept unless --set-repo-dir is given.

set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"
repo="$(cd "$here/.." && pwd -P)"
lib="$HOME/.local/lib/am-ops"
conf="$HOME/.config/am-ops"
units="$HOME/.config/systemd/user"
bin_dir="$HOME/.local/bin"

set_repo_dir=0
case "${1:-}" in
  --set-repo-dir) set_repo_dir=1 ;;
  "") ;;
  *) echo "usage: install.sh [--set-repo-dir]" >&2; exit 64 ;;
esac

mkdir -p "$lib/bin" "$lib/lib" "$conf" "$units" "$bin_dir"
install -m 755 "$here"/bin/*.sh "$lib/bin/"
install -m 644 "$here"/lib/*.sh "$lib/lib/"
if [ -e "$bin_dir/am-admin" ] && [ ! -L "$bin_dir/am-admin" ]; then
  echo "keeping existing non-link $bin_dir/am-admin" >&2
else
  ln -sfn "$lib/bin/am-admin.sh" "$bin_dir/am-admin"
fi
chmod 700 "$conf"
created_config=0
if [ ! -f "$conf/config.env" ]; then
  install -m 600 "$here/.env.example" "$conf/config.env"
  created_config=1
  echo "created $conf/config.env"
fi

# ── AM_REPO_DIR ─────────────────────────────────────────────────────────────
linked_worktree() {
  # A linked worktree's git dir (.git/worktrees/<name>) differs from the common one (.git).
  local git_dir common_dir
  git_dir=$(cd "$repo" && cd "$(git rev-parse --git-dir 2>/dev/null)" 2>/dev/null && pwd -P) || return 1
  common_dir=$(cd "$repo" && cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P) || return 1
  [ "$git_dir" != "$common_dir" ]
}
configured_repo_dir() {
  # The value as the ops scripts see it (the config is shell, sourced by common.sh),
  # canonical when the directory exists so a symlinked home compares equal.
  local value
  value=$( set +u; AM_REPO_DIR=""; . "$conf/config.env" >/dev/null 2>&1; printf '%s' "${AM_REPO_DIR:-}" )
  if [ -n "$value" ] && [ -d "$value" ]; then (cd "$value" && pwd -P); else printf '%s' "$value"; fi
}
write_repo_dir() {
  local line tmp
  line=$(printf 'AM_REPO_DIR=%q' "$repo")
  tmp=$(mktemp "$conf/config.env.XXXXXX")
  {
    grep -v '^[[:space:]]*AM_REPO_DIR=' "$conf/config.env" || true
    echo "# Recorded by ops/install.sh from the checkout it ran from."
    echo "$line"
  } >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$conf/config.env"
  echo "recorded $line in $conf/config.env"
}

current_repo_dir=$(configured_repo_dir)
if [ ! -f "$repo/docker-compose.yml" ]; then
  echo "not a deployment checkout ($repo has no docker-compose.yml); AM_REPO_DIR left as '${current_repo_dir}'" >&2
elif linked_worktree && [ "$set_repo_dir" != 1 ]; then
  echo "running from a linked git worktree ($repo); AM_REPO_DIR left as '${current_repo_dir}'" >&2
elif [ "$current_repo_dir" = "$repo" ]; then
  :
elif [ -z "$current_repo_dir" ] || [ "$created_config" = 1 ] || [ "$set_repo_dir" = 1 ]; then
  write_repo_dir
else
  echo "AM_REPO_DIR stays '$current_repo_dir' (this checkout: $repo); run with --set-repo-dir to switch" >&2
fi

docker_dir="$(dirname "$(command -v docker)")"

unit() {
  # unit NAME DESCRIPTION SCRIPT TIMER_LINES...
  local name="$1" description="$2" script="$3"
  shift 3
  cat >"$units/am-$name.service" <<EOF
[Unit]
Description=AssetManagement ops: $description

[Service]
Type=oneshot
Environment=PATH=$docker_dir:/usr/local/bin:/usr/bin:/bin
ExecStart=$lib/bin/$script
# Exit 2 means "primary copy good, a mirror failed": reported, not a failure.
SuccessExitStatus=2
EOF
  {
    echo "[Unit]"
    echo "Description=AssetManagement ops timer: $description"
    echo
    echo "[Timer]"
    printf '%s\n' "$@"
    echo
    echo "[Install]"
    echo "WantedBy=timers.target"
  } >"$units/am-$name.timer"
}

unit backup "database snapshot" am-backup.sh \
  "OnCalendar=hourly" "RandomizedDelaySec=120" "Persistent=true"
unit logs-archive "container log archive" am-logs-archive.sh \
  "OnBootSec=3min" "OnUnitActiveSec=10min"
unit watchdog "health check and restart" am-watchdog.sh \
  "OnBootSec=2min" "OnUnitActiveSec=1min" "AccuracySec=10s"
unit restore-verify "restore test of the newest snapshot" am-restore-verify.sh \
  "OnCalendar=Sun *-*-* 04:30:00" "Persistent=true"

systemctl --user daemon-reload
for name in backup logs-archive watchdog restore-verify; do
  systemctl --user enable --now "am-$name.timer"
done

echo "installed. status: $lib/bin/am-status.sh"
