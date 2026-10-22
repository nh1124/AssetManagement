#!/bin/bash
# Print ops state, timers and the admin console's published address.

AM_JOB=status
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"

python3 - "$AM_STATE_DIR/status" <<'PY'
import json, sys
from pathlib import Path

for path in sorted(Path(sys.argv[1]).glob("*.json")):
    status = json.loads(path.read_text(encoding="utf-8"))
    print(f"[{path.stem}]")
    for key in sorted(status):
        if status[key] != "":
            print(f"  {key}: {status[key]}")
PY

echo "[timers]"
systemctl --user list-timers 'am-*' --no-pager 2>/dev/null | sed 's/^/  /' || true

echo "[admin]"
if admin_ports=$(docker port finance-admin 8000 2>/dev/null); then
  while IFS= read -r mapping; do
    [ -n "$mapping" ] || continue
    printf '  %s\n' "$mapping"
    # Strip the final :port and Docker's brackets around IPv6 addresses.
    bind_address="${mapping%:*}"
    bind_address="${bind_address#[}"
    bind_address="${bind_address%]}"
    case "$bind_address" in
      127.0.0.1|::1) ;;
      *)
        if [ -z "$AM_ADMIN_ALLOWED_BIND" ] || [ "$bind_address" != "$AM_ADMIN_ALLOWED_BIND" ]; then
          echo "  WARNING: admin console published beyond loopback/VPN"
        fi
        ;;
    esac
  done <<< "$admin_ports"
else
  echo "  admin port unavailable (container absent or Docker unreachable)"
fi

echo "[snapshots]"
for tier in hourly daily weekly monthly; do
  count=$(find "$AM_BACKUP_ROOT/db/$tier" -name '*.dump' 2>/dev/null | wc -l)
  echo "  $tier: $count"
done
du -sh "$AM_BACKUP_ROOT" 2>/dev/null | sed 's/^/  total: /'
