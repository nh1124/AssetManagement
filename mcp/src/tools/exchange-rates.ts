// ============================================================
// Exchange rate tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const rateInputSchema = z
  .object({
    base_currency: z.string().min(3).max(10).describe("Base currency, e.g. USD"),
    quote_currency: z.string().min(3).max(10).describe("Quote currency, e.g. JPY"),
    rate: z.number().positive().describe("Exchange rate"),
    as_of_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("Rate date, YYYY-MM-DD"),
    source: z.string().optional().default("manual").describe("Rate source"),
  })
  .strict();

export function registerExchangeRateTools(server: McpServer): void {
  server.registerTool(
    "exchange_rates_list",
    {
      title: "List exchange rates",
      description: "Returns exchange rates, optionally filtered by base and quote currency.",
      inputSchema: z
        .object({
          base_currency: z.string().optional().describe("Base currency filter"),
          quote_currency: z.string().optional().describe("Quote currency filter"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ base_currency, quote_currency }) => {
      try {
        const params = new URLSearchParams();
        if (base_currency !== undefined) params.append("base_currency", base_currency);
        if (quote_currency !== undefined) params.append("quote_currency", quote_currency);
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/exchange-rates/${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ rates: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "exchange_rates_create",
    {
      title: "Create exchange rate",
      description: "Creates or upserts an exchange rate for a date.",
      inputSchema: rateInputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/exchange-rates/", input);
        return {
          content: [{ type: "text", text: `Saved exchange rate:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "exchange_rates_update",
    {
      title: "Update exchange rate",
      description: "Updates one exchange rate row.",
      inputSchema: rateInputSchema.partial().extend({
        id: z.number().int().min(1).describe("Exchange rate ID"),
      }),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const data = await api.put<unknown>(`/exchange-rates/${id}`, patch);
        return {
          content: [{ type: "text", text: `Updated exchange rate:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "exchange_rates_delete",
    {
      title: "Delete exchange rate",
      description: "Deletes one exchange rate row.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Exchange rate ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/exchange-rates/${id}`);
        return {
          content: [{ type: "text", text: `Deleted exchange rate ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "exchange_rates_auto_update",
    {
      title: "Auto-update used exchange rates",
      description: "Fetches today's rates for currencies used in journal transactions.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async () => {
      try {
        const data = await api.post<unknown>("/exchange-rates/auto-update", {});
        return {
          content: [{ type: "text", text: `Auto-updated exchange rates:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
