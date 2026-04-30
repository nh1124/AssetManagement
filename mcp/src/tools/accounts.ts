// ============================================================
// Account Tools — backed by FastAPI /accounts/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

interface Account {
  id: number;
  name: string;
  account_type: string;
  balance: number;
  budget_limit?: number | null;
  expected_return?: number | null;
}

export function registerAccountTools(server: McpServer): void {

  // ── accounts_list ──────────────────────────────────────────
  server.registerTool(
    "accounts_list",
    {
      title: "口座一覧（タイプ別）",
      description: `全口座をタイプ別（asset/liability/income/expense）にグループ化して返します。

Use when: 口座の一覧や残高を確認したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const data = await api.get<Record<string, Account[]>>("/accounts/by-type");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── accounts_update ────────────────────────────────────────
  server.registerTool(
    "accounts_update",
    {
      title: "口座残高・予算上限を更新",
      description: `指定IDの口座の残高または予算上限を更新します。

Use when: 口座の残高や予算上限を変更したいとき`,
      inputSchema: z.object({
        id: z.number().int().min(1).describe("口座ID"),
        balance: z.number().optional().describe("新しい残高（円）"),
        budget_limit: z.number().optional().describe("新しい予算上限（円）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ id, balance, budget_limit }) => {
      try {
        const body: Record<string, unknown> = {};
        if (balance !== undefined) body.balance = balance;
        if (budget_limit !== undefined) body.budget_limit = budget_limit;
        const data = await api.put<Account>(`/accounts/${id}`, body);
        return {
          content: [{ type: "text", text: `Updated account ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── accounts_net_worth ─────────────────────────────────────
  server.registerTool(
    "accounts_net_worth",
    {
      title: "純資産（ネットワース）計算",
      description: `全口座からasset・liabilityを抽出し、純資産（資産合計 - 負債合計）を計算します。

Use when: 現在の純資産や財務状況を確認したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const accounts = await api.get<Account[]>("/accounts/");
        const assets = accounts.filter(a => a.account_type === "asset");
        const liabilities = accounts.filter(a => a.account_type === "liability");
        const totalAssets = assets.reduce((s, a) => s + a.balance, 0);
        const totalLiabilities = liabilities.reduce((s, a) => s + a.balance, 0);
        const netWorth = totalAssets - totalLiabilities;

        const result = {
          net_worth: netWorth,
          total_assets: totalAssets,
          total_liabilities: totalLiabilities,
          assets: assets.map(a => ({ id: a.id, name: a.name, balance: a.balance })),
          liabilities: liabilities.map(a => ({ id: a.id, name: a.name, balance: a.balance }))
        };

        return {
          content: [{ type: "text", text: `純資産: ${netWorth.toLocaleString()}円\n資産合計: ${totalAssets.toLocaleString()}円\n負債合計: ${totalLiabilities.toLocaleString()}円\n\n${JSON.stringify(result, null, 2)}` }],
          structuredContent: toStructured(result)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
