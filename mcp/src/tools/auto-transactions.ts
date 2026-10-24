import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";
import { writeOrRequestChange } from "../write-control.js";

const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const inputSchema = z.object({
  name: z.string().min(1),
  kind: z.enum(["income", "expense", "debt", "transfer"]).optional(),
  amount: z.number().nonnegative(),
  currency: z.string().optional(),
  source_account_id: z.number().int().positive(),
  destination_account_id: z.number().int().positive(),
  budget_account_id: z.number().int().positive().nullable().optional(),
  repeat_mode: z.enum(["once", "count", "indefinite"]).optional(),
  frequency: z.enum(["Monthly", "Yearly", "EveryNDays"]).nullable().optional(),
  frequency_days: z.number().int().positive().nullable().optional(),
  day_of_month: z.number().int().min(1).max(31).nullable().optional(),
  month_of_year: z.number().int().min(1).max(12).nullable().optional(),
  start_date: date,
  end_date: date.nullable().optional(),
  repeat_count: z.number().int().min(1).max(100000).nullable().optional(),
  budget_active: z.boolean().optional(),
  is_active: z.boolean().optional(),
  records_transactions: z.boolean().optional().describe("取引も記録する: false for one that only budgets each month and never posts"),
  note: z.string().nullable().optional(),
}).strict();

export function registerAutoTransactionTools(server: McpServer): void {
  server.registerTool("auto_transactions_list", {
    title: "List automatic transactions", description: "Lists automatic transactions, including inactive and finished schedules.",
    inputSchema: z.object({}).strict(),
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, async () => {
    try {
      const data = await api.get<unknown>("/auto-transactions/");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ auto_transactions: data }) };
    } catch (error) { return { isError: true, content: [{ type: "text", text: String(error) }] }; }
  });
  server.registerTool("auto_transactions_create", {
    title: "Create automatic transaction", description: "Creates a schedule that posts automatically on each due date. The first date is on or after today; no past dates are backfilled.",
    inputSchema,
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  }, async (input) => {
    try {
      return await writeOrRequestChange("Created automatic transaction", () => api.post<unknown>("/auto-transactions/", input),
        { resource: "auto_transactions", action: "create", input_payload: input });
    } catch (error) { return { isError: true, content: [{ type: "text", text: String(error) }] }; }
  });
  server.registerTool("auto_transactions_update", {
    title: "Update automatic transaction", description: "Replaces the editable fields. Read the current schedule first and include all fields to keep. Re-activation starts on or after today.",
    inputSchema: inputSchema.extend({ id: z.number().int().positive() }).strict(),
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, async ({ id, ...input }) => {
    try {
      return await writeOrRequestChange("Updated automatic transaction", () => api.put<unknown>(`/auto-transactions/${id}`, input),
        { resource: "auto_transactions", action: "update", target_ref: { id }, input_payload: input });
    } catch (error) { return { isError: true, content: [{ type: "text", text: String(error) }] }; }
  });
  server.registerTool("auto_transactions_delete", {
    title: "Delete automatic transaction", description: "Deletes a schedule while preserving its posted transactions. Set is_active=false to stop it without deleting.",
    inputSchema: z.object({ id: z.number().int().positive() }).strict(),
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
  }, async ({ id }) => {
    try {
      await api.delete<unknown>(`/auto-transactions/${id}`);
      return { content: [{ type: "text", text: `Deleted automatic transaction ${id}` }], structuredContent: { id } };
    } catch (error) { return { isError: true, content: [{ type: "text", text: String(error) }] }; }
  });
}
