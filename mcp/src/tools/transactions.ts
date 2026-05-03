// ============================================================
// Transaction tools backed by FastAPI /transactions/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
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

interface Transaction {
  id: number;
  date: string;
  description: string;
  amount: number;
  type: z.infer<typeof transactionTypeSchema>;
  category?: string | null;
  currency?: string;
  from_account_id?: number | null;
  to_account_id?: number | null;
  from_account_name?: string | null;
  to_account_name?: string | null;
}

export function registerTransactionTools(server: McpServer): void {
  server.registerTool(
    "transactions_list",
    {
      title: "List transactions",
      description: "Returns transactions with optional date, type, category, amount, account, and text filters.",
      inputSchema: z
        .object({
          limit: z.number().int().min(1).max(500).optional().default(30).describe("Maximum number of rows"),
          offset: z.number().int().min(0).optional().default(0).describe("Rows to skip"),
          start_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Start date, YYYY-MM-DD"),
          end_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("End date, YYYY-MM-DD"),
          type: transactionTypeSchema.optional().describe("Transaction type"),
          category: z.string().optional().describe("Category contains this text"),
          amount_min: z.number().optional().describe("Minimum amount"),
          amount_max: z.number().optional().describe("Maximum amount"),
          account_id: z.number().int().min(1).optional().describe("From or to account ID"),
          q: z.string().optional().describe("Description contains this text"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ limit = 30, offset = 0, start_date, end_date, type, category, amount_min, amount_max, account_id, q }) => {
      try {
        const params = new URLSearchParams();
        params.append("limit", String(limit));
        params.append("offset", String(offset));
        if (start_date !== undefined) params.append("start_date", start_date);
        if (end_date !== undefined) params.append("end_date", end_date);
        if (type !== undefined) params.append("type", type);
        if (category !== undefined) params.append("category", category);
        if (amount_min !== undefined) params.append("amount_min", String(amount_min));
        if (amount_max !== undefined) params.append("amount_max", String(amount_max));
        if (account_id !== undefined) params.append("account_id", String(account_id));
        if (q !== undefined) params.append("q", q);

        const data = await api.get<Transaction[]>(`/transactions/?${params.toString()}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ transactions: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "transactions_create",
    {
      title: "Create transaction",
      description:
        "Creates and posts a transaction. This changes account balances through the backend journal processing.",
      inputSchema: z
        .object({
          date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("Transaction date, YYYY-MM-DD"),
          description: z.string().min(1).describe("Description"),
          amount: z.number().min(0).describe("Amount"),
          type: transactionTypeSchema.describe("Transaction type"),
          category: z.string().optional().describe("Category"),
          from_account_id: z.number().int().min(1).optional().describe("Source account ID"),
          to_account_id: z.number().int().min(1).optional().describe("Destination account ID"),
          currency: z.string().optional().default("JPY").describe("Currency"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
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
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "transactions_recent",
    {
      title: "Show recent transactions",
      description: "Returns the 10 newest transactions in a compact text summary.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<Transaction[]>("/transactions/?limit=10");
        if (!data || data.length === 0) {
          return { content: [{ type: "text", text: "No transactions found." }] };
        }
        const lines = data.map(
          (t) =>
            `${t.date}  ${t.type.padEnd(18)}  ${String(t.amount.toLocaleString()).padStart(12)} JPY  ${t.description}`,
        );
        const text = `Recent ${data.length} transactions:\n\n${lines.join("\n")}`;
        return {
          content: [{ type: "text", text }],
          structuredContent: toStructured({ transactions: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
