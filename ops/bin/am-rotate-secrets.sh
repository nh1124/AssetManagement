#!/bin/bash
# Replace the signing and encryption keys in .env and restart what uses them.
#
#   am-rotate-secrets.sh            show what would change
#   am-rotate-secrets.sh --apply    do it
#   am-rotate-secrets.sh --apply --all   also replace keys that are not the published defaults
#
# By default only keys that are missing or still equal to the development
# defaults are replaced: those values are in a public repository, and a token
# signed with them is accepted as any user.
#
# Effects of a run: everyone is signed out (web UI and MCP clients sign in
# again). Stored AI keys and MFA secrets keep working: the old encryption key
# stays readable as ENCRYPTION_KEY_PREVIOUS until the stored values have been
# re-encrypted, which this script does when the backend supports it.
#
# It refuses to run while backend/ or mcp/ have uncommitted changes, because
# the restart would start whatever is in the working tree.

AM_JOB=rotate-secrets
# shellcheck source=../lib/common.sh
. "$(dirname "$(readlink -f "$0")")/../lib/common.sh"

: "${AM_REPO_DIR:=$HOME/AssetManagement}"
: "${AM_BACKEND_CONTAINER:=finance-backend}"
: "${AM_ADMIN_CONTAINER:=finance-admin}"
# Overridable so the script can be exercised against a throwaway project.
: "${AM_COMPOSE:=docker compose}"
apply=0
all=0
force=0
for arg in "$@"; do
  case "$arg" in
    --apply) apply=1 ;;
    --all) all=1 ;;
    --force) force=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 64 ;;
  esac
done

env_file="$AM_REPO_DIR/.env"
[ -f "$env_file" ] || { echo "no .env at $env_file" >&2; exit 1; }

DEV_JWT="dev_jwt_secret_change_in_production_must_be_32_chars"
DEV_MCP="change-me-to-a-secret-key-at-least-32-chars"
DEV_ENC="YLM_ViHfrMWM0hUF3XoAMLLSaL4dVTy-JnHamAaIWTo="

# Empty when the key is absent; grep's "no match" status must not end the
# script half-way through a rotation.
current() { { grep -E "^$1=" "$env_file" || true; } | tail -n 1 | cut -d= -f2-; }
needs() {
  # needs NAME DEFAULT -> 0 when the key should be replaced
  local value
  value=$(current "$1")
  [ "$all" = 1 ] || [ -z "$value" ] || [ "$value" = "$2" ]
}
random_token() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }
random_fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }
set_env() {
  # set_env NAME VALUE -> replace the line, or append it
  AM_NAME="$1" AM_VALUE="$2" python3 - "$env_file" <<'PY'
import os, sys
path, name, value = sys.argv[1], os.environ["AM_NAME"], os.environ["AM_VALUE"]
lines = open(path, encoding="utf-8").read().splitlines()
kept = [line for line in lines if not line.startswith(name + "=")]
kept.append(f"{name}={value}")
with open(path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(kept) + "\n")
PY
}

plan=""
needs JWT_SECRET_KEY "$DEV_JWT" && plan="$plan JWT_SECRET_KEY"
needs MCP_JWT_SECRET "$DEV_MCP" && plan="$plan MCP_JWT_SECRET"
# The encryption key can only be replaced if the backend can read old values
# with a previous key; without that, stored MFA secrets become unreadable.
supports_previous=0
grep -q "encryption_key_previous" "$AM_REPO_DIR/backend/app/config.py" 2>/dev/null && supports_previous=1
if needs ENCRYPTION_KEY "$DEV_ENC"; then
  if [ "$supports_previous" = 1 ]; then
    plan="$plan ENCRYPTION_KEY"
  else
    echo "ENCRYPTION_KEY is still the published default, but this backend cannot keep a"
    echo "previous key readable. Not replacing it (it would lock out MFA). Merge the"
    echo "branch that adds ENCRYPTION_KEY_PREVIOUS, then run this again."
  fi
fi

if [ -z "$plan" ]; then
  echo "nothing to rotate"
  exit 0
fi
echo "would replace:$plan"
[ "$apply" = 1 ] || { echo "dry run; add --apply"; exit 0; }

if [ "$force" != 1 ]; then
  dirty=$(git -C "$AM_REPO_DIR" status --porcelain -- backend mcp docker-compose.yml | head -n 5)
  if [ -n "$dirty" ]; then
    echo "uncommitted changes under backend/, mcp/ or docker-compose.yml:" >&2
    echo "$dirty" >&2
    echo "the restart would run them. Commit or stash first, or pass --force." >&2
    exit 1
  fi
fi

log_event info start keys="$(echo "$plan" | xargs)"
backup="$env_file.bak-$(date +%Y%m%dT%H%M%S)"
cp -p "$env_file" "$backup"
chmod 600 "$backup" "$env_file"

rollback() {
  log_event error rolling_back reason="$1"
  cp -p "$backup" "$env_file"
  (cd "$AM_REPO_DIR" && $AM_COMPOSE up -d backend mcp admin) >/dev/null 2>&1 || true
  write_status rotate-secrets last_result=rolled_back last_error="$1" last_failure_at="$(date -Iseconds)"
  exit 1
}
# From here .env is being rewritten. Any failure, including one nobody
# anticipated, must put the old file back rather than leave new keys in .env
# with the old ones still running.
trap 'trap - ERR; rollback unexpected_error_line_$LINENO' ERR

case "$plan" in *JWT_SECRET_KEY*) set_env JWT_SECRET_KEY "$(random_token)" ;; esac
case "$plan" in *MCP_JWT_SECRET*) set_env MCP_JWT_SECRET "$(random_token)" ;; esac
old_encryption_key=""
case "$plan" in
  *ENCRYPTION_KEY*)
    old_encryption_key=$(current ENCRYPTION_KEY)
    [ -n "$old_encryption_key" ] || old_encryption_key="$DEV_ENC"
    previous=$(current ENCRYPTION_KEY_PREVIOUS)
    set_env ENCRYPTION_KEY_PREVIOUS "${old_encryption_key}${previous:+,$previous}"
    set_env ENCRYPTION_KEY "$(random_fernet)"
    ;;
esac

(cd "$AM_REPO_DIR" && $AM_COMPOSE up -d backend mcp admin) >/dev/null 2>&1 || rollback compose_up_failed

healthy=0
for _ in $(seq 1 60); do
  if [ "$(docker inspect -f '{{.State.Health.Status}}' "$AM_BACKEND_CONTAINER" 2>/dev/null)" = "healthy" ] \
    && [ "$(docker inspect -f '{{.State.Health.Status}}' "$AM_ADMIN_CONTAINER" 2>/dev/null)" = "healthy" ]; then
    healthy=1
    break
  fi
  sleep 3
done
[ "$healthy" = 1 ] || rollback backend_or_admin_not_healthy
# The keys are in use now; a later failure must not undo them.
trap - ERR

if [ -n "$old_encryption_key" ]; then
  # Rewrite the stored secrets under the new key. The previous key is left
  # in .env on purpose: remove it by hand once this has reported success and
  # a backup taken after this point exists.
  reencrypt_exit=0
  reencrypt_output=$(cd "$AM_REPO_DIR" && $AM_COMPOSE run --rm --no-deps migrate \
    python -m app.maintenance.reencrypt_secrets --apply 2>&1) || reencrypt_exit=$?
  printf '%s\n' "$reencrypt_output"
  if [ "$reencrypt_exit" -ne 0 ] || [[ ! "$reencrypt_output" =~ applied:\ rotated=[0-9]+\ unreadable=0($|[[:space:]]) ]]; then
    reencrypt_error="exit=$reencrypt_exit $reencrypt_output"
    log_event error reencrypt_incomplete error="$reencrypt_error"
    write_status rotate-secrets last_result=reencrypt_incomplete last_error="$reencrypt_error" \
      last_failure_at="$(date -Iseconds)" last_keys="$(echo "$plan" | xargs)" env_backup="$backup"
    echo "re-encryption failed or reported unreadable values; ENCRYPTION_KEY_PREVIOUS must stay" >&2
    exit 1
  fi
  log_event info reencrypted
fi

write_status rotate-secrets last_result=ok last_success_at="$(date -Iseconds)" \
  last_keys="$(echo "$plan" | xargs)" last_error="" env_backup="$backup"
log_event info end result=ok
echo "done. previous .env kept at $backup (contains the old keys; delete it when satisfied)"
