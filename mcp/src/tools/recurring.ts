// ============================================================
// Recurring transaction tools backed by FastAPI /recurring/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { fetchAccounts, previewTransactionPayload } from "../domain-guidance.js";
import { toStructured } from "../utils.js";

const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const transactionTypeSchema = z.enum([
  "Income",
  "Expense",
  "Transfer",
  "LiabilityPayment",
  "Borrowing",
  "CreditExpense",
  "CreditAssetPurchase",
]);

const recurringInputSchema = z
  .object({
    name: z.string().min(1).describe("Name"),
    amount: z.number().min(0).describe("Amount"),
    currency: z.string().optional().describe("Currency"),
    type: transactionTypeSchema.describe("Transaction type"),
    from_account_id: z.number().int().min(1).optional().describe("Source account ID"),
    to_account_id: z.number().int().min(1).optional().describe("Destination account ID"),
    frequency: z.enum(["Monthly", "Yearly"]).describe("Frequency"),
    day_of_month: z.number().int().min(1).max(31).optional().describe("Due day of month"),
    month_of_year: z.number().int().min(1).max(12).nullable().optional().describe("Month for yearly frequency"),
    next_due_date: dateSchema.nullable().optional().describe("Next due date"),
    start_period: z.string().regex(/^\d{4}-\d{2}$/).nullable().optional().describe("First active period, YYYY-MM"),
    end_period: z.string().regex(/^\d{4}-\d{2}$/).nullable().optional().describe("Last active period, YYYY-MM"),
    auto_post: z.boolean().optional().describe("Whether this recurring item is posted automatically when due"),
    is_active: z.boolean().optional().describe("Whether the recurring transaction is active"),
    source_registry_entry_id: z.number().int().min(1).nullable().optional().describe("Linked registry entry ID"),
  })
  .strict();

const recurringPatchSchema = recurringInputSchema.partial().extend({
  id: z.number().int().min(1).describe("Recurring transaction ID"),
});

const recurringPayloadKeys = [
  "name",
  "amount",
  "currency",
  "type",
  "from_account_id",
  "to_account_id",
  "frequency",
  "day_of_month",
  "month_of_year",
  "next_due_date",
  "start_period",
  "end_period",
  "auto_post",
  "is_active",
  "source_registry_entry_id",
] as const;

function recurringPayload(input: object): Record<string, unknown> {
  const source = input as Record<string, unknown>;
  const payload: Record<string, unknown> = {};
  for (const key of recurringPayloadKeys) {
    if (source[key] !== undefined) payload[key] = source[key];
  }
  return payload;
}

export function registerRecurringTools(server: McpServer): void {
  server.registerTool(
    "recurring_list",
    {
      title: "List recurring transactions",
      description: "Returns all recurring transaction definitions.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/recurring/");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ recurring: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "recurring_due",
    {
      title: "List due recurring transactions",
      description: "Returns active recurring transactions whose next_due_date is today or earlier.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/recurring/due");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ recurring: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "recurring_create",
    {
      title: "Create recurring transaction",
      description: "Creates a recurring transaction definition. This does not post a real transaction until processed.",
      inputSchema: recurringInputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/recurring/", recurringPayload(input));
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
    "recurring_preview",
    {
      title: "Preview recurring transaction",
      description:
        "Validates a recurring transaction definition and previews the transaction it would post when processed. Does not save or post anything.",
      inputSchema: recurringInputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const accounts = await fetchAccounts();
        const transactionPreview = previewTransactionPayload(
          {
            description: input.name,
            amount: input.amount,
            type: input.type,
            category: undefined,
            from_account_id: input.from_account_id,
            to_account_id: input.to_account_id,
            currency: input.currency ?? "JPY",
          },
          accounts,
        );
        const data = {
          ok_to_submit: transactionPreview.ok_to_submit,
          schedule_preview: {
            frequency: input.frequency,
            day_of_month: input.day_of_month ?? 1,
            month_of_year: input.month_of_year ?? null,
            next_due_date: input.next_due_date ?? null,
            is_active: input.is_active ?? true,
          },
          transaction_preview: transactionPreview,
          warnings: [
            ...(transactionPreview.validation.warnings ?? []),
            "recurring_create saves a definition only. Use recurring_process to post an actual transaction when due.",
          ],
        };
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
    "recurring_update",
    {
      title: "Update recurring transaction",
      description: "Partially updates a recurring transaction definition. Only provided fields are sent.",
      inputSchema: recurringPatchSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const data = await api.patch<unknown>(`/recurring/${id}`, recurringPayload(patch));
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
    "recurring_process",
    {
      title: "Process recurring transaction",
      description: "Posts one due recurring transaction and advances its next_due_date.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Recurring transaction ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/recurring/${id}/process`, {});
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
    "recurring_skip",
    {
      title: "Skip recurring transaction",
      description: "Advances one recurring transaction without posting it.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Recurring transaction ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/recurring/${id}/skip`, {});
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
