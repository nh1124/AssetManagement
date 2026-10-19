// ============================================================
// Account tools backed by FastAPI /accounts/
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
  is_active?: boolean;
}

const accountFields = {
  name: z.string().min(1).describe("Account name"),
  is_active: z.boolean().optional(),
  liability_closing_day: z.number().int().min(1).max(31).nullable().optional(),
  liability_payment_day: z.number().int().min(1).max(31).nullable().optional(),
  liability_payment_month_offset: z.number().int().min(0).max(24).optional(),
  liability_payment_policy: z.enum(["full", "minimum", "fixed", "installment", "revolving"]).optional(),
  liability_minimum_payment: z.number().min(0).nullable().optional(),
  liability_fixed_payment_amount: z.number().min(0).nullable().optional(),
  liability_installment_months: z.number().int().min(1).max(120).nullable().optional(),
  liability_revolving_rate: z.number().min(0).nullable().optional(),
};

export function registerAccountTools(server: McpServer): void {
  server.registerTool(
    "accounts_list",
    {
      title: "List accounts by type",
      description: "Returns active accounts grouped by asset/liability/income/expense, including journal-derived balances.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<Record<string, Account[]>>("/accounts/by-type");
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
    "accounts_create",
    {
      title: "Create account",
      description:
        "Creates an account. Opening balances must be created through transactions; this tool sends balance=0.",
      inputSchema: z
        .object({
          ...accountFields,
          account_type: z.enum(["asset", "liability", "income", "expense"]).describe("Account type"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const body = { ...input, balance: 0 };
        const data = await api.post<Account>("/accounts/", body);
        return {
          content: [{ type: "text", text: `Created account:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "accounts_update",
    {
      title: "Update account metadata",
      description:
        "Updates editable account metadata. Balances are journal-derived and must be changed through transactions, not this tool.",
      inputSchema: z
        .object({
          id: z.number().int().min(1).describe("Account ID"),
          ...z.object(accountFields).partial().shape,
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...body }) => {
      try {

        const data = await api.put<Account>(`/accounts/${id}`, body);
        return {
          content: [{ type: "text", text: `Updated account ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "accounts_delete",
    {
      title: "Deactivate account",
      description: "Soft-deletes an account by marking it inactive.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Account ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/accounts/${id}`);
        return {
          content: [{ type: "text", text: `Deactivated account ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );


  server.registerTool(
    "accounts_net_worth",
    {
      title: "Calculate net worth",
      description: "Calculates net worth from active asset and liability accounts using journal-derived balances.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const accounts = await api.get<Account[]>("/accounts/");
        const assets = accounts.filter((a) => a.account_type === "asset");
        const liabilities = accounts.filter((a) => a.account_type === "liability");
        const totalAssets = assets.reduce((sum, account) => sum + account.balance, 0);
        const totalLiabilities = liabilities.reduce((sum, account) => sum + account.balance, 0);
        const netWorth = totalAssets - totalLiabilities;

        const result = {
          net_worth: netWorth,
          total_assets: totalAssets,
          total_liabilities: totalLiabilities,
          assets: assets.map((a) => ({ id: a.id, name: a.name, balance: a.balance })),
          liabilities: liabilities.map((a) => ({ id: a.id, name: a.name, balance: a.balance })),
        };

        return {
          content: [
            {
              type: "text",
              text: `Net worth: ${netWorth.toLocaleString()} JPY\nAssets: ${totalAssets.toLocaleString()} JPY\nLiabilities: ${totalLiabilities.toLocaleString()} JPY\n\n${JSON.stringify(result, null, 2)}`,
            },
          ],
          structuredContent: toStructured(result),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
