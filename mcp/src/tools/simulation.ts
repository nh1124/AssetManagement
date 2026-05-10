// ============================================================
// Simulation config, Monte Carlo, and saved scenario tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const contributionScheduleSchema = z.array(z.record(z.unknown()));

const simulationConfigSchema = z
  .object({
    annual_return: z.number().optional().default(5).describe("Annual return percentage"),
    tax_rate: z.number().optional().default(20).describe("Tax rate percentage"),
    is_nisa: z.boolean().optional().default(true).describe("Whether NISA tax treatment is assumed"),
    monthly_savings: z.number().min(0).optional().default(100000).describe("Monthly savings amount"),
    volatility: z.number().min(0).optional().default(15).describe("Annual volatility percentage"),
    inflation_rate: z.number().optional().default(2).describe("Annual inflation percentage"),
  })
  .strict();

const scenarioCreateSchema = z
  .object({
    life_event_id: z.number().int().min(1).describe("Life event ID"),
    name: z.string().min(1).describe("Scenario name"),
    description: z.string().optional().describe("Scenario description"),
    annual_return: z.number().describe("Annual return percentage"),
    inflation: z.number().describe("Annual inflation percentage"),
    monthly_savings: z.number().min(0).optional().describe("Monthly savings override"),
    contribution_schedule: contributionScheduleSchema.optional().default([]).describe("Contribution schedule"),
    allocation_mode: z.enum(["weighted", "direct"]).optional().default("direct").describe("Allocation mode"),
  })
  .strict();

const scenarioUpdateSchema = scenarioCreateSchema.omit({ life_event_id: true }).partial().extend({
  id: z.number().int().min(1).describe("Scenario ID"),
});

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

  server.registerTool(
    "simulation_monte_carlo",
    {
      title: "Run Monte Carlo simulation",
      description: "Runs Monte Carlo simulation for one life event.",
      inputSchema: z
        .object({
          life_event_id: z.number().int().min(1).describe("Life event ID"),
          n_simulations: z.number().int().min(100).max(10000).optional().default(1000),
          annual_return: z.number().optional().describe("Annual return override"),
          inflation: z.number().optional().describe("Inflation override"),
          monthly_savings: z.number().min(0).optional().describe("Monthly savings override"),
          contribution_schedule: contributionScheduleSchema.optional().describe("Contribution schedule"),
          allocation_mode: z.enum(["weighted", "direct"]).optional().default("direct"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ life_event_id, n_simulations = 1000, annual_return, inflation, monthly_savings, contribution_schedule, allocation_mode = "direct" }) => {
      try {
        const params = new URLSearchParams();
        params.append("n_simulations", String(n_simulations));
        if (annual_return !== undefined) params.append("annual_return", String(annual_return));
        if (inflation !== undefined) params.append("inflation", String(inflation));
        if (monthly_savings !== undefined) params.append("monthly_savings", String(monthly_savings));
        if (contribution_schedule !== undefined) params.append("contribution_schedule", JSON.stringify(contribution_schedule));
        params.append("allocation_mode", allocation_mode);
        const data = await api.post<unknown>(`/simulation/monte-carlo/${life_event_id}?${params.toString()}`, {});
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
    "simulation_scenarios_list",
    {
      title: "List simulation scenarios",
      description: "Lists saved scenarios for one life event.",
      inputSchema: z.object({ life_event_id: z.number().int().min(1).describe("Life event ID") }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ life_event_id }) => {
      try {
        const data = await api.get<unknown>(`/simulation/scenarios?life_event_id=${life_event_id}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ scenarios: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "simulation_scenarios_create",
    {
      title: "Create simulation scenario",
      description: "Saves a scenario for one life event.",
      inputSchema: scenarioCreateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/simulation/scenarios", input);
        return {
          content: [{ type: "text", text: `Created simulation scenario:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "simulation_scenarios_update",
    {
      title: "Update simulation scenario",
      description: "Updates a saved simulation scenario.",
      inputSchema: scenarioUpdateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const data = await api.put<unknown>(`/simulation/scenarios/${id}`, patch);
        return {
          content: [{ type: "text", text: `Updated simulation scenario:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "simulation_scenarios_delete",
    {
      title: "Delete simulation scenario",
      description: "Deletes a saved simulation scenario.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Scenario ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/simulation/scenarios/${id}`);
        return {
          content: [{ type: "text", text: `Deleted simulation scenario ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "simulation_scenarios_compare",
    {
      title: "Compare simulation scenarios",
      description: "Compares two saved scenarios for one life event.",
      inputSchema: z
        .object({
          life_event_id: z.number().int().min(1).describe("Life event ID"),
          scenario_ids: z.array(z.number().int().min(1)).length(2).describe("Two scenario IDs [id1, id2]"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/simulation/scenarios/compare", input);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ comparison: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
