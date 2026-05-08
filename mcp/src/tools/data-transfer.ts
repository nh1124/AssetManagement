// ============================================================
// Data export/import tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

export function registerDataTransferTools(server: McpServer): void {
  server.registerTool(
    "data_export",
    {
      title: "Export current client data",
      description: "Exports all data for the current client as a portable JSON object.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/data/export");
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
    "data_import_replace_current_client",
    {
      title: "Import client data",
      description: "Replaces the current client's data with an exported data payload. Use only after explicit confirmation.",
      inputSchema: z
        .object({
          payload: z.record(z.unknown()).describe("Payload previously returned by data_export"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ payload }) => {
      try {
        const data = await api.post<unknown>("/data/import", payload);
        return {
          content: [{ type: "text", text: `Imported data:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
