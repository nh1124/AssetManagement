# AssetManagement Agent Instructions (Codex / Cowork 共通)

## 作業前に読むもの

1. [CLAUDE.md](CLAUDE.md) — プロジェクト共通の原則（実データ保護・Journal 不変条件）
2. [docs/agent_knowledge/README.md](docs/agent_knowledge/README.md) — 共通知識の索引
3. 実装タスクの場合: [docs/implementation-notes/codex/STATUS.md](docs/implementation-notes/codex/STATUS.md) — タスク状態の正本。`tasks/` 配下のみアクティブ。`archive/` は再実行禁止
4. MCP でデータ操作する場合: [.agents/skills/financeide-mcp/SKILL.md](.agents/skills/financeide-mcp/SKILL.md) — MCP 操作の手順書
5. データ入力代行の場合: [docs/agent_instruction/data_entry_agent_guide.md](docs/agent_instruction/data_entry_agent_guide.md)

## 原則

- 実データはユーザー資産。書き込み前に対象 client を必ず確認する。
- `Transaction` 作成時は必ず `JournalEntry` も作成する（API/MCP 経由なら自動。DB 直 INSERT 禁止）。
- Registry（`registry_entries`）が定常収支の正本。生成物の recurring / plan line を直接編集しない。
- 破壊的操作（delete / import replace）はユーザーの明示指示があるときのみ。

## 構成

- `backend/`: FastAPI + PostgreSQL（Docker, port 5434, DB=`finance_ide`）。Alembic は起動時に自動適用
- `frontend/`: Vite + React（desktop / mobile レイアウト）
- `mcp/`: MCP サーバ（stdio / streamable HTTP）。write ツール契約は `mcp/contracts/write-tools.json`
- 仕様: `docs/specs/`（vision / requirements / domain / design）

## 開発コマンド

リポジトリとツールチェーンは **WSL Ubuntu 側** (`~/AssetManagement`) にある。Windows の PowerShell / Git Bash には `docker` も Python も通っていないため、以下はすべて WSL 内で実行する。

- 起動: `docker compose --env-file .env up -d`
- 状態確認: `docker compose --env-file .env ps`（4 サービスすべて healthy が正常）
- backend テスト: `~/amvenv/bin/python -m pytest backend/tests`。SQLite インメモリで動くため Docker は不要
- venv の再作成: `python3 -m venv ~/amvenv && ~/amvenv/bin/pip install -r backend/requirements.txt pytest`
- auto-reload は既定で無効（起動が決定的になるため）。使う場合は `BACKEND_RELOAD=1 docker compose --env-file .env up -d backend`。無効のままコードを反映するには `docker compose --env-file .env restart backend`
- **Windows ファイルシステム上 (`/mnt/c/...`) にチェックアウトしない**こと。inotify が無いため auto-reload が `os error 5` で backend ごと落ち、ビルドも極端に遅くなる
- node の依存を入れ直すときは `npm install` ではなく **`npm ci`** を使う。`npm ci` は node_modules を削除してから入れ直すため、外部から紛れ込んだディレクトリが残らない
- `npm --prefix mcp run check:node-modules` で、lockfile に無いパッケージが node_modules に紛れていないか検査できる（過去に別リポジトリの workspace を再帰コピーで取り込み、20GB が 3 ヶ月放置された）
- 型チェック: `frontend/` と `mcp/` それぞれで `npx tsc --noEmit`
- MCP 契約チェック: `backend/tests/test_mcp_write_tool_contracts.py`

## 完了時

- 実装タスクは `STATUS.md` の該当行を更新し、完了タスクは `tasks/` から `archive/` へ移す。
- 完了報告は短く: 変更ファイル、テスト結果、登録/変更した ID のみ。
