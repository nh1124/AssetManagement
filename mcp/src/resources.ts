// ============================================================
// MCP resources
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { api } from "./api-client.js";

function jsonText(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

export function registerResources(server: McpServer): void {
  server.registerResource(
    "financial-summary",
    "asset-management://summary",
    {
      title: "Financial summary",
      description: "Current summary from /analysis/summary.",
      mimeType: "application/json",
    },
    async (uri) => {
      const data = await api.get<unknown>("/analysis/summary");
      return {
        contents: [{ uri: uri.href, mimeType: "application/json", text: jsonText(data) }],
      };
    },
  );

  server.registerResource(
    "recent-transactions",
    "asset-management://transactions/recent",
    {
      title: "Recent transactions",
      description: "Newest 10 transactions from /transactions/.",
      mimeType: "application/json",
    },
    async (uri) => {
      const data = await api.get<unknown>("/transactions/?limit=10");
      return {
        contents: [{ uri: uri.href, mimeType: "application/json", text: jsonText(data) }],
      };
    },
  );
}
