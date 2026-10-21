#!/bin/bash
# Remove the timers and the installed scripts. Snapshots, archived logs and the
# configuration are left where they are.

set -euo pipefail
units="$HOME/.config/systemd/user"

for name in backup logs-archive watchdog restore-verify; do
  systemctl --user disable --now "am-$name.timer" 2>/dev/null || true
  rm -f "$units/am-$name.service" "$units/am-$name.timer"
done
systemctl --user daemon-reload
rm -rf "$HOME/.local/lib/am-ops"
echo "removed timers and scripts; kept ~/.config/am-ops and the backup directory"
