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
# The audit log records who ran the command (cli:<host user>); inside the container
# the process user is the container's own.
exec_options+=(-e "AM_CLI_OPERATOR=$(id -un)")
exec docker compose exec "${exec_options[@]}" admin python -m app.admin.cli "$@"
