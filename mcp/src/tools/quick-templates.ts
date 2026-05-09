// ============================================================
// Quick template and transaction batch tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { fetchAccounts, previewTransactionPayload } from "../domain-guidance.js";
import { toStructured } from "../utils.js";

const transactionTypeSchema = z.enum([
  "Income",
  "Expense",
  "Transfer",
  "LiabilityPayment",
  "Borrowing",
  "CreditExpense",
  "CreditAssetPurchase",
]);

const transactionInputSchema = z
  .object({
    date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("Transaction date, YYYY-MM-DD"),
    description: z.string().min(1).optional().default("").describe("Description"),
    amount: z.number().min(0).describe("Amount"),
    type: transactionTypeSchema.describe("Transaction type"),
    category: z.string().optional().describe("Category"),
    currency: z.string().optional().default("JPY").describe("Currency"),
    from_account_id: z.number().int().min(1).optional().describe("Source account ID"),
    to_account_id: z.number().int().min(1).optional().describe("Destination account ID"),
  })
  .strict();

const quickTemplateCreateSchema = z
  .object({
    tray: z.string().min(1).describe("Template tray/group"),
    name: z.string().min(1).describe("Template display name"),
    template_kind: z.string().min(1).describe("Template kind"),
    description: z.string().optional().describe("Default description"),
    category: z.string().optional().describe("Default category"),
    default_currency: z.string().optional().default("JPY").describe("Default currency"),
    default_from_account_id: z.number().int().min(1).optional().describe("Default source account ID"),
    default_to_account_id: z.number().int().min(1).optional().describe("Default destination account ID"),
    config: z.record(z.unknown()).optional().default({}).describe("Template-specific config"),
    sort_order: z.number().int().optional().default(0).describe("Sort order within tray"),
    is_active: z.boolean().optional().default(true).describe("Whether the template is active"),
  })
  .strict();

const quickTemplateUpdateSchema = quickTemplateCreateSchema.partial().extend({
  id: z.number().int().min(1).describe("Quick template ID"),
});

export function registerQuickTemplateTools(server: McpServer): void {
  server.registerTool(
    "quick_templates_list",
    {
      title: "List quick templates",
      description: "Returns quick input templates, optionally filtered by tray.",
      inputSchema: z
        .object({
          tray: z.string().optional().describe("Tray/group filter"),
          include_inactive: z.boolean().optional().default(false).describe("Include inactive templates"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ tray, include_inactive = false }) => {
      try {
        const params = new URLSearchParams();
        if (tray !== undefined) params.append("tray", tray);
        params.append("include_inactive", String(include_inactive));
        const data = await api.get<unknown>(`/quick-templates/?${params.toString()}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ templates: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "quick_templates_create",
    {
      title: "Create quick template",
      description: "Creates a quick input template for repeated transaction entry.",
      inputSchema: quickTemplateCreateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/quick-templates/", input);
        return {
          content: [{ type: "text", text: `Created quick template:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "quick_templates_update",
    {
      title: "Update quick template",
      description: "Updates a quick input template.",
      inputSchema: quickTemplateUpdateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const data = await api.put<unknown>(`/quick-templates/${id}`, patch);
        return {
          content: [{ type: "text", text: `Updated quick template:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "quick_templates_delete",
    {
      title: "Deactivate quick template",
      description: "Soft-deletes a quick template by marking it inactive.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Quick template ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/quick-templates/${id}`);
        return {
          content: [{ type: "text", text: `Deactivated quick template ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "transaction_batches_list",
    {
      title: "List transaction batches",
      description: "Returns recent transaction batches created from quick input or agent workflows.",
      inputSchema: z
        .object({
          limit: z.number().int().min(1).max(500).optional().default(50),
          offset: z.number().int().min(0).optional().default(0),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ limit = 50, offset = 0 }) => {
      try {
        const data = await api.get<unknown>(`/transaction-batches/?limit=${limit}&offset=${offset}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ batches: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "transaction_batches_get",
    {
      title: "Get transaction batch",
      description: "Returns one transaction batch including its transactions.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Batch ID") }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.get<unknown>(`/transaction-batches/${id}`);
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
    "transaction_batches_create",
    {
      title: "Create transaction batch",
      description: "Creates and posts multiple transactions as one batch. Backend journal processing is applied.",
      inputSchema: z
        .object({
          quick_template_id: z.number().int().min(1).optional().describe("Source quick template ID"),
          label: z.string().optional().describe("Batch label"),
          source: z.string().optional().default("mcp").describe("Batch source"),
          input_payload: z.record(z.unknown()).optional().default({}).describe("Original input payload"),
          transactions: z.array(transactionInputSchema).min(1).describe("Transactions to create"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/transaction-batches/", input);
        return {
          content: [{ type: "text", text: `Created transaction batch:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "transaction_batches_preview",
    {
      title: "Preview transaction batch",
      description:
        "Validates and previews all transactions in a batch without saving or posting them. Use before transaction_batches_create.",
      inputSchema: z
        .object({
          quick_template_id: z.number().int().min(1).optional().describe("Source quick template ID"),
          label: z.string().optional().describe("Batch label"),
          source: z.string().optional().default("mcp").describe("Batch source"),
          input_payload: z.record(z.unknown()).optional().default({}).describe("Original input payload"),
          transactions: z.array(transactionInputSchema).min(1).describe("Transactions to preview"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const accounts = await fetchAccounts();
        const previews = input.transactions.map((transaction, index) => ({
          index,
          ...previewTransactionPayload(transaction, accounts),
        }));
        const data = {
          ok_to_submit: previews.every((preview) => preview.ok_to_submit),
          batch: {
            quick_template_id: input.quick_template_id ?? null,
            label: input.label ?? null,
            source: input.source ?? "mcp",
            transaction_count: input.transactions.length,
            total_amount: input.transactions.reduce((sum, transaction) => sum + transaction.amount, 0),
          },
          previews,
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
}
