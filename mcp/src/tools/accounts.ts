// ============================================================
// Account tools backed by FastAPI /accounts/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const accountRoleSchema = z.enum(["defense", "growth", "earmarked", "operating", "unassigned"]);

interface Account {
  id: number;
  name: string;
  account_type: string;
  balance: number;
  rollup_balance?: number;
  parent_id?: number | null;
  expected_return?: number | null;
  role?: z.infer<typeof accountRoleSchema>;
  role_target_amount?: number | null;
  is_active?: boolean;
}

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
    "accounts_update",
    {
      title: "Update account metadata",
      description:
        "Updates editable account metadata. Balances are journal-derived and must be changed through transactions, not this tool.",
      inputSchema: z
        .object({
          id: z.number().int().min(1).describe("Account ID"),
          name: z.string().min(1).optional().describe("Account name"),
          parent_id: z.number().int().min(1).nullable().optional().describe("Parent account ID, or null for top level"),
          expected_return: z.number().optional().describe("Expected annual return percentage"),
          role: accountRoleSchema.optional().describe("Planning role"),
          role_target_amount: z.number().nullable().optional().describe("Target amount for the planning role"),
          is_active: z.boolean().optional().describe("Whether the account is active"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, name, parent_id, expected_return, role, role_target_amount, is_active }) => {
      try {
        const body: Record<string, unknown> = {};
        if (name !== undefined) body.name = name;
        if (parent_id !== undefined) body.parent_id = parent_id;
        if (expected_return !== undefined) body.expected_return = expected_return;
        if (role !== undefined) body.role = role;
        if (role_target_amount !== undefined) body.role_target_amount = role_target_amount;
        if (is_active !== undefined) body.is_active = is_active;

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
