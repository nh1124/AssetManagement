# AssetManagement Agent Instructions (Codex / Cowork 共通)

## 作業前に読むもの

1. [CLAUDE.md](CLAUDE.md) — プロジェクト共通の原則（実データ保護・Journal 不変条件）
2. [docs/README.md](docs/README.md) — 文書の構成と「何の正本はどれか」。`docs/specs/` が現行仕様、`docs/archive/` は旧仕様（仕様として読まない）
3. [docs/agents/README.md](docs/agents/README.md) — AI 向けの共通知識の索引
4. 実装タスクの場合: [docs/work/README.md](docs/work/README.md)（進め方）と [docs/work/STATUS.md](docs/work/STATUS.md)（進行中・残りの正本）
5. MCP でデータ操作する場合: [.agents/skills/financeide-mcp/SKILL.md](.agents/skills/financeide-mcp/SKILL.md) — MCP 操作の手順書
6. データ入力代行の場合: [docs/agents/data_entry_guide.md](docs/agents/data_entry_guide.md)

## 原則

- 実データはユーザー資産。書き込み前に対象 client を必ず確認する。
- `Transaction` 作成時は必ず `JournalEntry` も作成する（API/MCP 経由なら自動。DB 直 INSERT 禁止）。
- 自動取引（`registry_entries`、MCP は `auto_transactions_*`）が決まった取引の正本。有効なものは期日に必ず記帳される。ゴール（と物品の取り置き）が書いた計画行は計画への反映（`plan_reflection_*`）が作り直す。直接編集しない。
- 破壊的操作（delete / import replace）はユーザーの明示指示があるときのみ。

## 構成

- `backend/`: FastAPI + PostgreSQL（Docker, port 5434, DB=`finance_ide`）。migration は compose の `migrate` サービスが `up -d` のときに適用する
- `frontend/`: Vite + React（desktop / mobile レイアウト）
- `mcp/`: MCP サーバ（stdio / streamable HTTP）。write ツール契約は `mcp/contracts/write-tools.json`
- 仕様: `docs/specs/`（vision / system_overview / layering / ai_write_path / ai_data_access_catalog / admin_console）。全体像は `docs/specs/system_overview.md`

## 開発コマンド

リポジトリとツールチェーンは **WSL Ubuntu 側** (`~/AssetManagement`) にある。Windows の PowerShell / Git Bash には `docker` も Python も通っていないため、以下はすべて WSL 内で実行する。

- 起動: `docker compose --env-file .env up -d`
- 状態確認: `docker compose --env-file .env ps`（4 サービスすべて healthy が正常）
- backend テスト: `~/amvenv/bin/python -m pytest backend/tests`。SQLite インメモリで動くため Docker は不要
- venv の再作成: `python3 -m venv ~/amvenv && ~/amvenv/bin/pip install -r backend/requirements.txt pytest`
- auto-reload は既定で無効（起動が決定的になるため）。コードを反映するには `docker compose --env-file .env build` → `docker compose --env-file .env up -d`（`restart backend` では migration も DB の権限の付与も走らない）。手順の全体は `docs/work/README.md` の「取り込みと反映」
- **Windows ファイルシステム上 (`/mnt/c/...`) にチェックアウトしない**こと。inotify が無いため auto-reload が `os error 5` で backend ごと落ち、ビルドも極端に遅くなる
- node の依存を入れ直すときは `npm install` ではなく **`npm ci`** を使う。`npm ci` は node_modules を削除してから入れ直すため、外部から紛れ込んだディレクトリが残らない
- `npm --prefix mcp run check:node-modules` で、lockfile に無いパッケージが node_modules に紛れていないか検査できる（過去に別リポジトリの workspace を再帰コピーで取り込み、20GB が 3 ヶ月放置された）
- 型チェック: `frontend/` は `npx tsc -b`（`tsc --noEmit` は何も検査しない）、`mcp/` は `npm run build`
- MCP 契約チェック: `backend/tests/test_mcp_write_tool_contracts.py`

## 完了時

- 実装タスクは `docs/work/STATUS.md` の該当行を更新し、振る舞いが変わったら `docs/specs/system_overview.md` を今の姿に書き換える（手順は `docs/work/README.md` の「文書の更新」）。
- 完了報告は短く: 変更ファイル、テスト結果、登録/変更した ID のみ。
