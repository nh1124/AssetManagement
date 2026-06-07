// ============================================================
// AI helper tools backed by /api/analyze
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
  "recurring_transactions",
  "goals",
  "products",
  "registry_entries",
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

  server.registerTool(
    "ai_analyze_text",
    {
      title: "Analyze transaction text",
      description: "Uses the configured Gemini key to extract transactions, recurring rules, or product updates from text.",
      inputSchema: z
        .object({
          text: z.string().min(1).describe("User text, receipt text, or purchase history text to analyze"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async ({ text }) => {
      try {
        const data = await api.post<unknown>("/api/analyze/", { parts: [{ text }] });
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ extracted: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_suggest_budget",
    {
      title: "Suggest budget",
      description: "Uses recent spending history and Gemini to suggest category budgets.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async () => {
      try {
        const data = await api.post<unknown>("/api/analyze/suggest-budget", {});
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ suggestions: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "ai_optimize_allocations",
    {
      title: "Optimize goal allocations",
      description: "Uses goals and asset accounts with Gemini to suggest goal allocations.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async () => {
      try {
        const data = await api.post<unknown>("/api/analyze/optimize-allocations", {});
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ suggestions: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
