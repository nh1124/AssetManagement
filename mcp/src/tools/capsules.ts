// ============================================================
// Capsule (savings goal) Tools — backed by FastAPI /capsules/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

interface Capsule {
  id: number;
  name: string;
  target_amount: number;
  monthly_contribution: number;
  current_balance: number;
  progress_pct: number;
}

export function registerCapsuleTools(server: McpServer): void {

  // ── capsules_list ──────────────────────────────────────────
  server.registerTool(
    "capsules_list",
    {
      title: "貯蓄カプセル一覧",
      description: `全貯蓄カプセルを一覧表示します（進捗率付き）。

Use when: 貯蓄目標の進捗を確認したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async () => {
      try {
        const data = await api.get<Capsule[]>("/capsules/");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ capsules: data })
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── capsules_create ────────────────────────────────────────
  server.registerTool(
    "capsules_create",
    {
      title: "貯蓄カプセル作成",
      description: `新しい貯蓄カプセル（目標貯蓄）を作成します。

Use when: 新しい貯蓄目標を作りたいとき`,
      inputSchema: z.object({
        name: z.string().min(1).describe("カプセル名"),
        target_amount: z.number().min(1).describe("目標金額（円）"),
        monthly_contribution: z.number().min(0).describe("月額積立額（円）"),
        current_balance: z.number().min(0).optional().default(0).describe("現在残高（円、デフォルト0）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async ({ name, target_amount, monthly_contribution, current_balance = 0 }) => {
      try {
        const data = await api.post<Capsule>("/capsules/", { name, target_amount, monthly_contribution, current_balance });
        return {
          content: [{ type: "text", text: `Created capsule:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── capsules_update ────────────────────────────────────────
  server.registerTool(
    "capsules_update",
    {
      title: "貯蓄カプセル更新",
      description: `既存の貯蓄カプセルを更新します。

Use when: カプセルの目標額・月額・残高を変更したいとき`,
      inputSchema: z.object({
        id: z.number().int().min(1).describe("カプセルID"),
        name: z.string().min(1).optional().describe("カプセル名"),
        target_amount: z.number().min(1).optional().describe("目標金額（円）"),
        monthly_contribution: z.number().min(0).optional().describe("月額積立額（円）"),
        current_balance: z.number().min(0).optional().describe("現在残高（円）")
      }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    },
    async ({ id, name, target_amount, monthly_contribution, current_balance }) => {
      try {
        const body: Record<string, unknown> = {};
        if (name !== undefined) body.name = name;
        if (target_amount !== undefined) body.target_amount = target_amount;
        if (monthly_contribution !== undefined) body.monthly_contribution = monthly_contribution;
        if (current_balance !== undefined) body.current_balance = current_balance;
        const data = await api.put<Capsule>(`/capsules/${id}`, body);
        return {
          content: [{ type: "text", text: `Updated capsule ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data)
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );

  // ── capsules_process ───────────────────────────────────────
  server.registerTool(
    "capsules_process",
    {
      title: "月次積立処理",
      description: `全カプセルに月額積立を自動加算します。

Use when: 月次の積立処理を実行したいとき`,
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
    },
    async () => {
      try {
        const data = await api.post<unknown>("/capsules/process_contributions", {});
        return {
          content: [{ type: "text", text: `Monthly contributions processed:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data ?? {})
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    }
  );
}
