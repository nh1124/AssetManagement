// ============================================================
// Exchange rate tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

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
      title: "Refresh tracked exchange rates",
      description: "Fetches the latest rates for every tracked currency against the client base currency.",
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
  server.registerTool(
    "fx_tracked_currencies_list",
    {
      title: "List tracked currencies",
      description: "Lists tracked currencies.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>(`/exchange-rates/tracked`);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ currencies: data }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
  server.registerTool(
    "fx_tracked_currencies_create",
    {
      title: "Track currency",
      description: "Validates a currency with Frankfurter and fetches its latest rate.",
      inputSchema: z.object({ currency: z.string().regex(/^[A-Za-z]{3}$/) }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async ({ currency }) => {
      try {
        const data = await api.post<unknown>(`/exchange-rates/tracked`, { currency });
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ currencies: data }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
  server.registerTool(
    "fx_tracked_currencies_delete",
    {
      title: "Stop tracking currency",
      description: "Removes tracking; stored exchange rates stay.",
      inputSchema: z.object({ currency: z.string().regex(/^[A-Za-z]{3}$/) }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ currency }) => {
      try {
        const data = await api.delete<unknown>(`/exchange-rates/tracked/${currency}`);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ currencies: data }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
