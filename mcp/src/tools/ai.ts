// ============================================================
// Context tools for AI agents (read-only summaries of this client's data)
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const aiContextResourceSchema = z.enum([
  "summary",
  "accounts",
  "transactions_recent",
  "monthly_plan",
  "goals",
  "products",
  "auto_transactions",
  "settings",
  "audit_logs",
]);

export function registerAiTools(server: McpServer): void {
  server.registerTool(
    "ai_context_resources",
    {
      title: "List AI context resources",
      description: "Lists the backend-approved AI context resources and their data classifications.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/ai/context/resources");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ resources: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_context_summary",
    {
      title: "Get AI context summary",
      description: "Returns a backend-approved AI-safe financial context summary.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/ai/context/summary");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ context: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_context_resource",
    {
      title: "Get AI context resource",
      description: "Returns one backend-approved AI-safe context resource. Data export is intentionally unavailable here.",
      inputSchema: z
        .object({
          resource: aiContextResourceSchema.describe("AI context resource to fetch"),
          limit: z.number().int().min(1).max(500).optional().describe("Maximum rows for list resources"),
          period: z.string().regex(/^\d{4}-\d{2}$/).optional().describe("Target month for monthly_plan, formatted YYYY-MM"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ resource, limit, period }) => {
      try {
        const params = new URLSearchParams();
        if (limit !== undefined) params.set("limit", String(limit));
        if (period) params.set("period", period);
        const query = params.toString();
        const data = await api.get<unknown>(`/ai/context/resource/${encodeURIComponent(resource)}${query ? `?${query}` : ""}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ context: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
