// ============================================================
// Action tools backed by FastAPI /actions/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

export function registerActionTools(server: McpServer): void {
  server.registerTool(
    "actions_list",
    {
      title: "List action bridges",
      description: "Returns saved action bridges, optionally filtered by source and target periods.",
      inputSchema: z
        .object({
          source_period: z.string().optional().describe("Source period such as YYYY-MM"),
          target_period: z.string().optional().describe("Target period such as YYYY-MM"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ source_period, target_period }) => {
      try {
        const params = new URLSearchParams();
        if (source_period !== undefined) params.append("source_period", source_period);
        if (target_period !== undefined) params.append("target_period", target_period);
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/actions/${query}`);
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
    "actions_process_due",
    {
      title: "Process due actions",
      description: "Applies all due action bridges for the current user.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.post<unknown>("/actions/process-due", {});
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
    "actions_apply",
    {
      title: "Apply action",
      description: "Applies one action bridge by ID.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Action ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/actions/${id}/apply`, {});
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
    "actions_skip",
    {
      title: "Skip action",
      description: "Skips one action bridge by ID.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Action ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.post<unknown>(`/actions/${id}/skip`, {});
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
