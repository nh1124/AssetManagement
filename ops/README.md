# ops — backup, log archive, watchdog

Four scheduled jobs that keep the system recoverable. They run as systemd user
timers and live outside the repository once installed, so they keep working
while the working tree is mid-edit.

| Job | Schedule | What it does |
|---|---|---|
| `am-backup` | hourly | `pg_dump` (custom format) + roles + manifest. Verified with `pg_restore --list` before it is kept. Tiers: hourly / daily / weekly / monthly. |
| `am-logs-archive` | every 10 min | Copies container logs out of Docker, which loses them on every recreate. One file per container per day, gzip after the day closes. |
| `am-watchdog` | every minute | Restarts a container that stays unhealthy (bounded: 3 per hour). Reports, but does not start, one that was stopped. Warns on a full disk and on a backup that stopped arriving. |
| `am-restore-verify` | Sunday 04:30 | Restores the newest snapshot into a throwaway PostgreSQL and compares row counts and ledger totals with the manifest. A snapshot whose alembic revision is not the live database's is not restored; it is recorded as `skipped` (see below). |

## Install / update

```bash
ops/install.sh
```

Copies the scripts to `~/.local/lib/am-ops/`, creates
`~/.config/am-ops/config.env` once, and enables the timers. Run it again after
changing anything under `ops/`.

## Look

```bash
~/.local/lib/am-ops/bin/am-status.sh
```

Each job writes `~/.local/state/am-ops/status/<job>.json`. Those files are the
interface: an admin screen should read them, not parse logs. Every job also
appends JSON lines (`start` / `end` / `error`) to `~/.local/state/am-ops/ops.log`.

## Restore verification and older snapshots

`am-restore-verify` checks the snapshot's manifest first. When the alembic
revision recorded at dump time differs from the live database's (the snapshot
predates a migration, e.g. every dump before 2026-10-13), it does not restore
it: the status file gets `last_result: skipped`, `skip_reason:
schema_not_current`, and both revisions. The next hourly dump after a
migration is at the current revision again, so a scheduled run only skips in
the hour after a deploy. An older snapshot can still be restored by hand as
below; it is just not compared against today's checks.

## A container log that cannot be read forward

A json-file log damaged mid-file (finance-backend's, since the unclean Docker
Desktop stop on 2026-10-09) makes `docker logs` and `docker logs --since` stop
at the damage with exit 0 and no error, while `docker logs --tail N` still
reads everything after it. `am-logs-archive` compares each forward read with
the newest lines and, when it stopped short, takes the rest from `--tail`
(`AM_LOG_TAIL_START`, doubling up to `AM_LOG_TAIL_MAX`). Such a container is
listed in `containers_stuck`, the run is `degraded` rather than `ok`, and
ops.log gets `forward_read_stuck` when it starts and once a day while it lasts,
plus `logs_gap` for any span no read could reach. A recreated container starts
a clean log file (`forward_read_recovered`); until then read its history with
`docker logs --tail`, not `--since`.

## Restore

```bash
# newest snapshot
ls ~/backups/assetmanagement/db/hourly/*.dump | tail -1

# into the running database container, replacing the current contents
docker exec -i finance-db dropdb -U postgres --if-exists finance_ide_restore
docker exec -i finance-db createdb -U postgres finance_ide_restore
docker exec -i finance-db pg_restore -U postgres -d finance_ide_restore --no-owner < FILE.dump
# inspect finance_ide_restore, then swap the names while the backend is stopped
```

Restoring into a second database first, then renaming, keeps the current data
until the restored copy has been looked at.

## Rotate the keys

```bash
~/.local/lib/am-ops/bin/am-rotate-secrets.sh            # what would change
~/.local/lib/am-ops/bin/am-rotate-secrets.sh --apply    # do it
```

Replaces `JWT_SECRET_KEY`, `MCP_JWT_SECRET` and `ENCRYPTION_KEY` when they are
missing or still the development defaults, recreates the backend, MCP and admin
containers, and puts the old `.env` back if the backend or admin does not come up
healthy (recreating all three again on rollback). Everyone is signed out.
Stored MFA secrets keep working:
the old encryption key stays readable as `ENCRYPTION_KEY_PREVIOUS` while
`app.maintenance.reencrypt_secrets` rewrites them under the new one through
`docker compose run --rm --no-deps migrate` as `am_owner`. Re-encryption failure
or unreadable values return a non-zero exit and `last_result=reencrypt_incomplete`;
`ENCRYPTION_KEY_PREVIOUS` must stay until re-encryption succeeds.

It refuses to run while `backend/` or `mcp/` have uncommitted changes, because
the restart would start whatever is in the working tree.

## Configuration

`~/.config/am-ops/config.env`; every key is described in
[.env.example](.env.example); additional defaults are in `lib/common.sh`.

- `AM_MIRROR_DIRS` — extra copies. A folder synced by Google Drive for desktop,
  a NAS mount, or an `sshfs`/`rclone mount` of a VPS all work the same way.
- `AM_GPG_PASSPHRASE_FILE` — encrypts the mirror copies. Set it before a mirror
  leaves this machine, and keep the passphrase somewhere that survives losing
  the machine.
- `AM_HEARTBEAT_URL_*` — fetched after each successful run. A monitoring
  service that alerts when the pings stop is the only thing that notices the
  whole machine being off.

## 管理コンソール

ブラウザで <http://admin.localhost:18300> を開きます。
専用のホスト名と Cookie の `/admin/api` パスで、管理セッションが利用者サービスへ送信されるのを防ぎます。
利用者サービスには `admin.localhost` を使わないでください。初回の管理者は
`am-admin admin create <name>` で作成します（パスワード・TOTP の対話入力）。
`ops/install.sh` は CLI をインストールし、`~/.local/bin/am-admin` をリンクします。
`~/.local/bin` を PATH に追加し、ops 設定の `AM_REPO_DIR` をデプロイ先に合わせてください。
Compose のプロジェクト名を指定した環境では、CLI 実行時も同じ
`COMPOSE_PROJECT_NAME` を設定します。

公開先は必ず loopback または VPN のアドレスだけに限定してください。
`0.0.0.0`・LAN・パブリックへの公開は禁止です。VPN 利用時は `.env` の
`ADMIN_BIND` と管理用 hosts/origins を明示し、ops 設定の
`AM_ADMIN_ALLOWED_BIND` に同じ VPN IP（ポートなし）を設定します。
`am-status.sh` の `[admin]` が公開ポートと範囲外公開の警告を表示します。
既存の ops 設定が `AM_CONTAINERS` を指定している場合は、手動で
`finance-admin` を追加してください。

開発時の `npm --prefix frontend run dev:admin` は <http://admin.localhost:15380> です。
API に渡す `ADMIN_ALLOWED_ORIGINS` にその origin を明示的に追加します
（設定例はルートの `.env.example`）。既定の許可範囲は変更しません。

## DB のロール

各プロセスは別の DB ロールで接続します（権限の正本は `backend/app/db_access.py`）。
`am_owner`（表の持ち主。migrate サービスだけ）、`am_user_app`（利用者 backend）、
`am_admin_app`（管理 backend と CLI）。利用者 backend は管理者の表・監査ログ・
システム設定の書き込み・アカウントの停止／承認ができず、DDL も実行できません。

初めて入れるとき（既存の DB は表の持ち主が `postgres`）:

```bash
# 0. バックアップ（am-backup が最新か、または pg_dump を取る）
# 1. .env に 3 つのパスワード（英数字のみ・32 文字以上・互いに別）
#    AM_DB_OWNER_PASSWORD / AM_DB_USER_APP_PASSWORD / AM_DB_ADMIN_APP_PASSWORD（openssl rand -hex 32）
ops/bin/am-db-roles.sh            # 何をするか表示（パスワードは伏せる）
ops/bin/am-db-roles.sh --apply    # ロールを作り、表の持ち主を am_owner へ（1 トランザクション）
docker compose --env-file .env up -d   # migrate が alembic と権限の付与を行い、backend・admin が起動
```

パスワードを替えるときは `.env` を変えて `am-db-roles.sh --apply` をもう一度実行し、
migrate・backend・admin を作り直します。バックアップ（`am-backup`）とリストア検証は
コンテナ内のローカルソケットで `postgres` として動くので影響を受けません
（リストア検証は `--no-owner --no-privileges` で復元します）。

superuser の `POSTGRES_PASSWORD` も強い値に変更してください。既存 DB では先に
`docker exec -it finance-db psql -U postgres -d finance_ide` のローカルソケットで
`ALTER ROLE postgres PASSWORD '...';` を実行し、`.env` の値を合わせます。
現在の Compose は `db/pg_hba.conf` を読み取り専用で指定し、`postgres` の TCP 接続を
IPv4・IPv6 とも拒否します（ホストの公開ポートからも不可）。ops と `am-db-roles.sh` は
`docker exec` 内のローカルソケット接続を使い続けます。

戻すとき: 以前のコミットの `docker-compose.yml` に戻して `up -d` すれば、
アプリは `postgres` で接続します（表の持ち主が `am_owner` でも superuser は読み書きできます）。
ロールは残しておいてかまいません。`hba_file` の上書きは現在の Compose にだけあるため、
戻すと DB はデータディレクトリ内の元の `pg_hba.conf` を再び使い、superuser の TCP 拒否も解除されます。

## What the watchdog will not do

It never runs `docker compose up`. Recreating containers from the working tree
could start code or migrations that are still being edited; a restart reuses
the container as it was built.

It does not start a container that was stopped. Docker's `unless-stopped`
policy already restarts anything that crashed, so a container that stays
stopped was stopped on purpose.

To pause recovery altogether while working on the stack:

```bash
touch ~/.local/state/am-ops/maintenance     # and remove it when done
```
