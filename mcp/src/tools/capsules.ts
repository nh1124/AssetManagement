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

const transactionTypeSchema = z.enum([
  "Income",
  "Expense",
  "Transfer",
  "LiabilityPayment",
  "Borrowing",
  "CreditExpense",
  "CreditAssetPurchase",
]);

const capsuleRuleInputSchema = z
  .object({
    capsule_id: z.number().int().min(1).describe("Capsule ID"),
    trigger_type: transactionTypeSchema.describe("Transaction type that triggers the rule"),
    trigger_category: z.string().nullable().optional().describe("Optional category substring"),
    trigger_description: z.string().nullable().optional().describe("Optional description substring"),
    source_mode: z.enum(["transaction_account", "fixed_account"]).optional().default("transaction_account"),
    source_account_id: z.number().int().min(1).nullable().optional().describe("Required when source_mode is fixed_account"),
    amount_type: z.enum(["fixed", "percentage"]).optional().default("fixed"),
    amount_value: z.number().min(0).describe("Fixed amount or percentage"),
    is_active: z.boolean().optional().default(true),
  })
  .strict();

const capsuleRuleUpdateSchema = capsuleRuleInputSchema
  .partial()
  .extend({ id: z.number().int().min(1).describe("Rule ID") })
  .strict();

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

  server.registerTool(
    "capsules_delete",
    {
      title: "Delete capsule",
      description: "Deletes a manual capsule. LifeEvent and product reserve capsules may be protected by the backend.",
      inputSchema: z
        .object({
          id: z.number().int().min(1).describe("Capsule ID"),
          transfer_account_id: z.number().int().min(1).optional().describe("Destination account for balances when required"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id, transfer_account_id }) => {
      try {
        const query = transfer_account_id !== undefined ? `?transfer_account_id=${transfer_account_id}` : "";
        const data = await api.delete<unknown>(`/capsules/${id}${query}`);
        return {
          content: [{ type: "text", text: `Deleted capsule ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data ?? { id }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_rules_list",
    {
      title: "List capsule rules",
      description: "Lists automatic allocation rules for Strategy capsules.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/capsules/rules");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ rules: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_rules_create",
    {
      title: "Create capsule rule",
      description: "Creates an automatic allocation rule for a capsule.",
      inputSchema: capsuleRuleInputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/capsules/rules", input);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_rules_update",
    {
      title: "Update capsule rule",
      description: "Updates an automatic allocation rule. Omitted fields are left unchanged by the backend.",
      inputSchema: capsuleRuleUpdateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const data = await api.put<unknown>(`/capsules/rules/${id}`, patch);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_rules_delete",
    {
      title: "Delete capsule rule",
      description: "Deletes an automatic allocation rule.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Rule ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/capsules/rules/${id}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data ?? { id }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_holdings_list",
    {
      title: "List capsule holdings",
      description: "Lists account holdings assigned to one capsule.",
      inputSchema: z.object({ capsule_id: z.number().int().min(1).describe("Capsule ID") }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ capsule_id }) => {
      try {
        const data = await api.get<unknown>(`/capsules/${capsule_id}/holdings`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ holdings: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_holdings_upsert",
    {
      title: "Upsert capsule holding",
      description: "Creates or replaces the holding amount for an account in one capsule.",
      inputSchema: z
        .object({
          capsule_id: z.number().int().min(1).describe("Capsule ID"),
          account_id: z.number().int().min(1).describe("Account ID"),
          held_amount: z.number().min(0).describe("Amount held for this capsule"),
          note: z.string().nullable().optional(),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ capsule_id, ...body }) => {
      try {
        const data = await api.post<unknown>(`/capsules/${capsule_id}/holdings`, body);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_holdings_update",
    {
      title: "Update capsule holding",
      description: "Updates a capsule holding amount or note.",
      inputSchema: z
        .object({
          capsule_id: z.number().int().min(1).describe("Capsule ID"),
          holding_id: z.number().int().min(1).describe("Holding ID"),
          held_amount: z.number().min(0).optional(),
          note: z.string().nullable().optional(),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ capsule_id, holding_id, ...body }) => {
      try {
        const data = await api.put<unknown>(`/capsules/${capsule_id}/holdings/${holding_id}`, body);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "capsule_holdings_delete",
    {
      title: "Delete capsule holding",
      description: "Deletes one account holding from a capsule.",
      inputSchema: z
        .object({
          capsule_id: z.number().int().min(1).describe("Capsule ID"),
          holding_id: z.number().int().min(1).describe("Holding ID"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ capsule_id, holding_id }) => {
      try {
        const data = await api.delete<unknown>(`/capsules/${capsule_id}/holdings/${holding_id}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data ?? { capsule_id, holding_id }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
