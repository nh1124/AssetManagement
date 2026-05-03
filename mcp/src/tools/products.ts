// ============================================================
// Product tools backed by FastAPI /products/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

export function registerProductTools(server: McpServer): void {
  server.registerTool(
    "products_list",
    {
      title: "List products",
      description: "Returns products with unit economics fields, optionally filtered by category or asset flag.",
      inputSchema: z
        .object({
          category: z.string().optional().describe("Exact category filter"),
          is_asset: z.boolean().optional().describe("Filter by asset/consumable"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ category, is_asset }) => {
      try {
        const params = new URLSearchParams();
        if (category !== undefined) params.append("category", category);
        if (is_asset !== undefined) params.append("is_asset", String(is_asset));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/products/${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ products: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "products_unit_economics_summary",
    {
      title: "Get unit economics summary",
      description: "Returns monthly consumable cost estimates by item and category.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/products/unit-economics-summary");
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
