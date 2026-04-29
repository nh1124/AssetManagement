// ============================================================
// Decision Log Tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { getDecisionLog, saveDecisionLog } from "../store.js";
import { toStructured } from "../utils.js";
import type { Decision } from "../types.js";
import crypto from "crypto";

function generateId(): string {
  return `d${Date.now().toString(36)}_${crypto.randomBytes(3).toString("hex")}`;
}

export function registerDecisionTools(server: McpServer): void {

  // ── decisions_list ─────────────────────────────────────────
  server.registerTool(
    "decisions_list",
    {
      title: "意思決定ログ一覧",
      description: `過去の投資意思決定の記録を一覧取得します。

Use when: 過去の判断の経緯を確認したいとき / 方針変更の履歴確認`,
      inputSchema: z.object({
        category: z.enum(["nisa", "dc", "holdings", "budget", "strategy", "other"]).optional().describe("フィルタするカテゴリ"),
        limit: z.number().int().min(1).max(100).optional().default(20).describe("取得件数（デフォルト20）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ category, limit = 20 }) => {
      try {
        const log = getDecisionLog();
        let decisions = [...log.decisions].reverse();
        if (category) decisions = decisions.filter(d => d.category === category);
        decisions = decisions.slice(0, limit);

        const result = { total: log.decisions.length, returned: decisions.length, filter_category: category ?? "all", decisions };
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── decisions_add ──────────────────────────────────────────
  server.registerTool(
    "decisions_add",
    {
      title: "意思決定を記録",
      description: `新しい投資意思決定をログに追記します。

Use when: 投資方針変更・新規口座設定など重要な決定を記録するとき`,
      inputSchema: z.object({
        category: z.enum(["nisa", "dc", "holdings", "budget", "strategy", "other"]).describe("カテゴリ"),
        title: z.string().min(1).max(100).describe("決定のタイトル"),
        description: z.string().min(1).describe("決定内容の詳細"),
        rationale: z.string().min(1).describe("判断理由・根拠"),
        outcome: z.string().optional().describe("結果・振り返り（後から追記可）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ category, title, description, rationale, outcome }) => {
      try {
        const log = getDecisionLog();
        const decision: Decision = {
          id: generateId(),
          date: new Date().toISOString().split("T")[0],
          category, title, description, rationale, outcome
        };
        log.decisions.push(decision);
        saveDecisionLog(log);

        return {
          content: [{ type: "text", text: `✅ 意思決定を記録しました (ID: ${decision.id})\n[${decision.date}] [${decision.category}] ${decision.title}\n\n${JSON.stringify(decision, null, 2)}` }],
          structuredContent: toStructured(decision)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── decisions_update_outcome ───────────────────────────────
  server.registerTool(
    "decisions_update_outcome",
    {
      title: "意思決定の結果を更新",
      description: `既存の意思決定レコードに結果・振り返りを追記します。

Use when: 後から結果を追記するとき`,
      inputSchema: z.object({
        id: z.string().min(1).describe("決定ID"),
        outcome: z.string().min(1).describe("結果・振り返り内容")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ id, outcome }) => {
      try {
        const log = getDecisionLog();
        const decision = log.decisions.find(d => d.id === id);
        if (!decision) return { content: [{ type: "text", text: `Error: ID "${id}" の決定が見つかりません。` }] };

        decision.outcome = outcome;
        saveDecisionLog(log);
        return {
          content: [{ type: "text", text: `✅ 結果を更新しました (ID: ${id})\n\n${JSON.stringify(decision, null, 2)}` }],
          structuredContent: toStructured(decision)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── decisions_get_latest ───────────────────────────────────
  server.registerTool(
    "decisions_get_latest",
    {
      title: "最新の意思決定を取得",
      description: `カテゴリ別に最新の意思決定を取得します。各カテゴリの直近の判断を素早く確認できます。

Use when: 直近の判断を素早く把握したいとき / コンテキスト把握`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const log = getDecisionLog();
        const categories: Decision["category"][] = ["nisa", "dc", "holdings", "budget", "strategy", "other"];
        const latestByCategory: Record<string, Decision | null> = {};
        for (const cat of categories) {
          latestByCategory[cat] = [...log.decisions].reverse().find(d => d.category === cat) ?? null;
        }
        const mostRecent = log.decisions.length > 0 ? log.decisions[log.decisions.length - 1] : null;
        const result = { total_decisions: log.decisions.length, most_recent: mostRecent, latest_by_category: latestByCategory };

        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
