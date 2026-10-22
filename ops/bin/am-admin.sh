#!/bin/bash
# Run the audited administrator CLI in the configured repository's admin service.

AM_JOB=admin
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"

: "${AM_REPO_DIR:=$HOME/AssetManagement}"
cd "$AM_REPO_DIR"

exec_options=()
if [ ! -t 0 ]; then
  exec_options+=(-T)
fi
exec docker compose exec "${exec_options[@]}" admin python -m app.admin.cli "$@"
