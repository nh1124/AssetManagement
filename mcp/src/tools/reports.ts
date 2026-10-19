// ============================================================
// Report tools backed by FastAPI /reports/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

export function registerReportTools(server: McpServer): void {
  server.registerTool(
    "reports_monthly",
    {
      title: "Get monthly report",
      description: "Returns the generated monthly financial report for a year and month.",
      inputSchema: z
        .object({
          year: z.number().int().min(2000).max(2100).optional().describe("Year; defaults to current year"),
          month: z.number().int().min(1).max(12).optional().describe("Month; defaults to current month"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ year, month }) => {
      try {
        const params = new URLSearchParams();
        if (year !== undefined) params.append("year", String(year));
        if (month !== undefined) params.append("month", String(month));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/reports/monthly${query}`);
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
    "reports_period",
    {
      title: "Get period report",
      description: "Returns the generated financial report for an arbitrary inclusive date range.",
      inputSchema: z
        .object({
          start_date: dateSchema.describe("Start date, YYYY-MM-DD"),
          end_date: dateSchema.describe("End date, YYYY-MM-DD"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ start_date, end_date }) => {
      try {
        const params = new URLSearchParams({ start_date, end_date });
        const data = await api.get<unknown>(`/reports/period?${params.toString()}`);
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
