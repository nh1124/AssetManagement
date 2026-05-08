// ============================================================
// Client and settings tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

export function registerClientTools(server: McpServer): void {
  server.registerTool(
    "clients_list",
    {
      title: "List clients",
      description: "Returns clients with masked AI config and general settings.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/clients/");
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ clients: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "clients_create",
    {
      title: "Create client",
      description: "Creates a new client profile, optionally seeding default accounts.",
      inputSchema: z
        .object({
          name: z.string().min(1).describe("Client display name"),
          seed_defaults: z.boolean().optional().default(true).describe("Seed default accounts"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/clients/", input);
        return {
          content: [{ type: "text", text: `Created client:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "clients_update_settings",
    {
      title: "Update current client settings",
      description: "Updates general settings for the authenticated current client.",
      inputSchema: z
        .object({
          client_id: z.number().int().min(1).describe("Current client ID"),
          general_settings: z.record(z.unknown()).describe("Settings to merge"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ client_id, general_settings }) => {
      try {
        const data = await api.put<unknown>(`/clients/${client_id}/settings`, { general_settings });
        return {
          content: [{ type: "text", text: `Updated client settings:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "clients_update_gemini_key",
    {
      title: "Update Gemini API key",
      description: "Stores an encrypted Gemini API key for a client. Avoid calling unless the user explicitly provides the key.",
      inputSchema: z
        .object({
          client_id: z.number().int().min(1).describe("Client ID"),
          gemini_api_key: z.string().min(1).describe("Gemini API key"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
    },
    async ({ client_id, gemini_api_key }) => {
      try {
        const data = await api.put<unknown>(`/clients/${client_id}/key`, { gemini_api_key });
        return {
          content: [{ type: "text", text: `Updated Gemini API key:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
