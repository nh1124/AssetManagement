// ============================================================
// Transaction batch tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { dateSchema, fetchAccounts, previewTransactionPayload, transactionPayloadSchema } from "../domain-guidance.js";
import { toStructured } from "../utils.js";

// One transaction inside a batch, with the same legs as a standalone one.
const transactionInputSchema = transactionPayloadSchema.extend({
  date: dateSchema.describe("Transaction date, YYYY-MM-DD"),
  description: z.string().min(1).optional().default("").describe("Description"),
});

export function registerTransactionBatchTools(server: McpServer): void {
  server.registerTool(
    "transaction_batches_list",
    {
      title: "List transaction batches",
      description: "Returns recent transaction batches created by agent workflows.",
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
