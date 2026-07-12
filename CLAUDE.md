# AssetManagement Claude Code Instructions

作業前に以下を読むこと:

- [docs/agent_knowledge/README.md](docs/agent_knowledge/README.md) — 共通知識の索引
  - `agent_behavior.md`: 協働で確認された判断基準（P/L 赤字・残高 ¥0 の誤読防止、Capsule 確認、報告フォーマット等）
  - `asset_management_system.md`: システム構成・Capsule の罠・登録ルール
- データ入力代行（Transaction / Item / Journal 登録）のタスクは [docs/agent_instruction/data_entry_agent_guide.md](docs/agent_instruction/data_entry_agent_guide.md) に従う
- MCP 経由のデータ操作は [.agents/skills/financeide-mcp/SKILL.md](.agents/skills/financeide-mcp/SKILL.md) に従う（codex / cowork 共通。エントリポイントは [AGENTS.md](AGENTS.md)）
- 実装タスクの状態は [docs/implementation-notes/codex/STATUS.md](docs/implementation-notes/codex/STATUS.md) が正本

原則: 実データはユーザー資産。登録前に対象 client を必ず確認し、`Transaction` 作成時は必ず `JournalEntry` も作成する。

Memory 運用: セッション中に確定した意思決定・罠・嗜好（3 行以内の事実）は、Workbench MCP が使える場合は該当プロジェクト（AssetFormation / Beauty 等）に `projects_memory_append` で記録する。長文は従来通り docs / artifacts へ。
