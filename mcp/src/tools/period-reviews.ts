// ============================================================
// Period review tools backed by FastAPI /period-reviews/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

interface PeriodReview {
  id: number;
  start_date: string;
  end_date: string;
  label: string;
  reflection: string;
  next_actions: string;
  created_at: string;
  updated_at?: string | null;
}

export function registerPeriodReviewTools(server: McpServer): void {
  server.registerTool(
    "period_reviews_get",
    {
      title: "Get period review",
      description: "Returns the saved review for a date range, or an empty draft if none exists.",
      inputSchema: z
        .object({
          start_date: dateSchema.optional().describe("Start date, YYYY-MM-DD; defaults to current month"),
          end_date: dateSchema.optional().describe("End date, YYYY-MM-DD; defaults to current month"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ start_date, end_date }) => {
      try {
        const params = new URLSearchParams();
        if (start_date !== undefined) params.append("start_date", start_date);
        if (end_date !== undefined) params.append("end_date", end_date);
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<PeriodReview>(`/period-reviews/${query}`);
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
    "period_reviews_upsert",
    {
      title: "Save period review",
      description: "Creates or updates reflection and next actions for a date range.",
      inputSchema: z
        .object({
          start_date: dateSchema.describe("Start date, YYYY-MM-DD"),
          end_date: dateSchema.describe("End date, YYYY-MM-DD"),
          label: z.string().optional().default("").describe("Optional display label"),
          reflection: z.string().optional().default("").describe("Reflection text"),
          next_actions: z.string().optional().default("").describe("Next actions text"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ start_date, end_date, label = "", reflection = "", next_actions = "" }) => {
      try {
        const data = await api.put<PeriodReview>("/period-reviews/", {
          start_date,
          end_date,
          label,
          reflection,
          next_actions,
        });
        return {
          content: [{ type: "text", text: `Saved period review:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
