#!/bin/bash
# Print the state of the ops jobs. Reads only the status files and the timers.

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

echo "[snapshots]"
for tier in hourly daily weekly monthly; do
  count=$(find "$AM_BACKUP_ROOT/db/$tier" -name '*.dump' 2>/dev/null | wc -l)
  echo "  $tier: $count"
done
du -sh "$AM_BACKUP_ROOT" 2>/dev/null | sed 's/^/  total: /'
