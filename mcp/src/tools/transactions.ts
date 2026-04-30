// ============================================================
// Transaction Tools — backed by FastAPI /transactions/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

interface Transaction {
  id: number;
  date: string;
  description: string;
  amount: number;
  type: string;
  category?: string | null;
  currency?: string;
  from_account_id?: number | null;
  to_account_id?: number | null;
}

export function registerTransactionTools(server: McpServer): void {

  // ── transactions_list ──────────────────────────────────────
  server.registerTool(
    "transactions_list",
    {
      title: "取引一覧",
      description: `取引一覧を取得します。期間・件数でフィルタリング可能。

Use when: 取引履歴を確認したいとき`,
      inputSchema: z.object({
        limit: z.number().int().min(1).max(500).optional().default(30).describe("取得件数（デフォルト30）"),
        start_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("開始日（YYYY-MM-DD）"),
        end_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("終了日（YYYY-MM-DD）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ limit = 30, start_date, end_date }) => {
      try {
        const params = new URLSearchParams();
        params.append("limit", String(limit));
        if (start_date !== undefined) params.append("start_date", start_date);
        if (end_date !== undefined) params.append("end_date", end_date);
        const data = await api.get<Transaction[]>(`/transactions/?${params.toString()}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ transactions: data })
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── transactions_create ────────────────────────────────────
  server.registerTool(
    "transactions_create",
    {
      title: "取引登録",
      description: `新しい取引（収入・支出・振替など）を登録します。

Use when: 取引を記録したいとき`,
      inputSchema: z.object({
        date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("取引日（YYYY-MM-DD）"),
        description: z.string().min(1).describe("取引の説明"),
        amount: z.number().min(0).describe("金額"),
        type: z.enum(["Income", "Expense", "Transfer", "LiabilityPayment"]).describe("取引タイプ"),
        category: z.string().optional().describe("カテゴリ"),
        from_account_id: z.number().int().min(1).optional().describe("出金元口座ID"),
        to_account_id: z.number().int().min(1).optional().describe("入金先口座ID"),
        currency: z.string().optional().default("JPY").describe("通貨（デフォルト: JPY）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ date, description, amount, type, category, from_account_id, to_account_id, currency = "JPY" }) => {
      try {
        const body: Record<string, unknown> = { date, description, amount, type, currency };
        if (category !== undefined) body.category = category;
        if (from_account_id !== undefined) body.from_account_id = from_account_id;
        if (to_account_id !== undefined) body.to_account_id = to_account_id;
        const data = await api.post<Transaction>("/transactions/", body);
        return {
          content: [{ type: "text", text: `Created transaction:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── transactions_recent ────────────────────────────────────
  server.registerTool(
    "transactions_recent",
    {
      title: "直近10件の取引サマリー",
      description: `最新10件の取引をテキスト形式で素早く確認します。

Use when: 最近の取引を手軽に把握したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const data = await api.get<Transaction[]>("/transactions/?limit=10");
        if (!data || data.length === 0) {
          return { content: [{ type: "text", text: "取引データがありません。" }] };
        }
        const lines = data.map(t =>
          `${t.date}  ${t.type.padEnd(18)}  ${String(t.amount.toLocaleString()).padStart(12)}円  ${t.description}`
        );
        const text = `直近${data.length}件の取引:\n\n${lines.join("\n")}`;
        return {
          content: [{ type: "text", text }],
          structuredContent: toStructured({ transactions: data })
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
