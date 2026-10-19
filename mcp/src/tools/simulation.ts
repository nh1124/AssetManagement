// ============================================================
// Client-wide simulation settings (tax, volatility, defaults)
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const simulationConfigSchema = z
  .object({
    annual_return: z.number().optional().default(5).describe("Annual return percentage"),
    tax_rate: z.number().optional().default(20).describe("Tax rate percentage"),
    is_nisa: z.boolean().optional().default(true).describe("Whether NISA tax treatment is assumed"),
    volatility: z.number().min(0).optional().default(15).describe("Annual volatility percentage"),
    inflation_rate: z.number().optional().default(2).describe("Annual inflation percentage"),
  })
  .strict();

export function registerSimulationTools(server: McpServer): void {
  server.registerTool(
    "simulation_config_get",
    {
      title: "Get simulation config",
      description: "Returns the current simulation configuration.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/simulation/config");
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
    "simulation_config_update",
    {
      title: "Update simulation config",
      description: "Creates or updates the current simulation configuration.",
      inputSchema: simulationConfigSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.put<unknown>("/simulation/config", input);
        return {
          content: [{ type: "text", text: `Updated simulation config:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
