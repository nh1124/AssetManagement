#!/bin/bash
# Install the ops jobs for the current user. Safe to run again after an update.
#
# The scripts are copied out of the repository on purpose: the timers must
# keep working while the working tree is mid-edit, on another branch, or gone.
#
#   scripts  -> ~/.local/lib/am-ops/
#   config   -> ~/.config/am-ops/config.env   (created once, never overwritten)
#   timers   -> ~/.config/systemd/user/am-*.{service,timer}

set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"
lib="$HOME/.local/lib/am-ops"
conf="$HOME/.config/am-ops"
units="$HOME/.config/systemd/user"
bin_dir="$HOME/.local/bin"

mkdir -p "$lib/bin" "$lib/lib" "$conf" "$units" "$bin_dir"
install -m 755 "$here"/bin/*.sh "$lib/bin/"
install -m 644 "$here"/lib/*.sh "$lib/lib/"
if [ -e "$bin_dir/am-admin" ] && [ ! -L "$bin_dir/am-admin" ]; then
  echo "keeping existing non-link $bin_dir/am-admin" >&2
else
  ln -sfn "$lib/bin/am-admin.sh" "$bin_dir/am-admin"
fi
chmod 700 "$conf"
if [ ! -f "$conf/config.env" ]; then
  install -m 600 "$here/.env.example" "$conf/config.env"
  echo "created $conf/config.env"
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
