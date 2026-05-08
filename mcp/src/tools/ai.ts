// ============================================================
// AI helper tools backed by /api/analyze
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

export function registerAiTools(server: McpServer): void {
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
