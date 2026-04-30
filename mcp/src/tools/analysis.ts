// ============================================================
// Analysis Tools — backed by FastAPI /analysis/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

export function registerAnalysisTools(server: McpServer): void {

  // ── analysis_summary ───────────────────────────────────────
  server.registerTool(
    "analysis_summary",
    {
      title: "財務サマリー",
      description: `純資産・月次損益・目標達成確率・実質キャッシュ・貯蓄率を返します。

Use when: 財務全体の現状を一目で把握したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const data = await api.get<unknown>("/analysis/summary");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── analysis_balance_sheet ─────────────────────────────────
  server.registerTool(
    "analysis_balance_sheet",
    {
      title: "貸借対照表",
      description: `指定月の資産・負債一覧を返します。

Use when: 特定月の資産・負債状況を確認したいとき`,
      inputSchema: z.object({
        year: z.number().int().min(2000).max(2100).optional().describe("年（省略時: 当月）"),
        month: z.number().int().min(1).max(12).optional().describe("月（省略時: 当月）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ year, month }) => {
      try {
        const params = new URLSearchParams();
        if (year !== undefined) params.append("year", String(year));
        if (month !== undefined) params.append("month", String(month));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/analysis/balance-sheet${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── analysis_profit_loss ───────────────────────────────────
  server.registerTool(
    "analysis_profit_loss",
    {
      title: "損益計算書",
      description: `指定月の収入・支出一覧を返します。

Use when: 特定月の収支を確認したいとき`,
      inputSchema: z.object({
        year: z.number().int().min(2000).max(2100).optional().describe("年（省略時: 当月）"),
        month: z.number().int().min(1).max(12).optional().describe("月（省略時: 当月）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ year, month }) => {
      try {
        const params = new URLSearchParams();
        if (year !== undefined) params.append("year", String(year));
        if (month !== undefined) params.append("month", String(month));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/analysis/profit-loss${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── analysis_variance ──────────────────────────────────────
  server.registerTool(
    "analysis_variance",
    {
      title: "予算差異分析",
      description: `指定月のカテゴリ別予算vs実績の差異を返します。

Use when: 予算の使いすぎ・余りを確認したいとき`,
      inputSchema: z.object({
        year: z.number().int().min(2000).max(2100).optional().describe("年（省略時: 当月）"),
        month: z.number().int().min(1).max(12).optional().describe("月（省略時: 当月）")
      }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ year, month }) => {
      try {
        const params = new URLSearchParams();
        if (year !== undefined) params.append("year", String(year));
        if (month !== undefined) params.append("month", String(month));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/analysis/variance${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
