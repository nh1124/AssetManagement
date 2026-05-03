// ============================================================
// Roadmap tools backed by FastAPI /roadmap/
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const simulationBasisSchema = z.enum(["annual_plan", "deterministic", "p10", "p50", "p90"]);
const simulationIntervalSchema = z.enum(["annual", "semiannual", "quarterly", "target_only"]);
const simulationModeSchema = z.enum(["add", "replace"]);

const milestoneSimulationInputSchema = z
  .object({
    life_event_id: z.number().int().min(1).describe("Life event ID"),
    basis: simulationBasisSchema.optional().default("p50").describe("Simulation basis"),
    interval: simulationIntervalSchema.optional().default("annual").describe("Milestone interval"),
    mode: simulationModeSchema.optional().default("replace").describe("Whether to add or replace generated milestones"),
    n_simulations: z.number().int().min(100).max(10000).optional().default(1000).describe("Monte Carlo simulations"),
    annual_return: z.number().nullable().optional().describe("Expected annual return override"),
    inflation: z.number().nullable().optional().describe("Inflation override"),
    monthly_savings: z.number().min(0).nullable().optional().describe("Monthly savings override"),
  })
  .strict();

export function registerRoadmapTools(server: McpServer): void {
  server.registerTool(
    "roadmap_projection",
    {
      title: "Get roadmap projection",
      description: "Returns a long-range projection of net worth and goal progress.",
      inputSchema: z
        .object({
          years: z.number().int().min(1).max(60).optional().default(30).describe("Projection years"),
          annual_return: z.number().optional().default(5.0).describe("Expected annual return percentage"),
          inflation: z.number().optional().default(2.0).describe("Inflation percentage"),
          monthly_savings: z.number().min(0).optional().describe("Monthly savings override"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ years = 30, annual_return = 5.0, inflation = 2.0, monthly_savings }) => {
      try {
        const params = new URLSearchParams({
          years: String(years),
          annual_return: String(annual_return),
          inflation: String(inflation),
        });
        if (monthly_savings !== undefined) params.append("monthly_savings", String(monthly_savings));
        const data = await api.get<unknown>(`/roadmap/projection?${params.toString()}`);
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
    "roadmap_milestones_list",
    {
      title: "List milestones",
      description: "Returns roadmap milestones, optionally filtered by life event.",
      inputSchema: z
        .object({
          life_event_id: z.number().int().min(1).optional().describe("Life event ID"),
          limit: z.number().int().min(1).max(500).optional().default(100).describe("Maximum rows"),
          skip: z.number().int().min(0).optional().default(0).describe("Rows to skip"),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ life_event_id, limit = 100, skip = 0 }) => {
      try {
        const params = new URLSearchParams({ limit: String(limit), skip: String(skip) });
        if (life_event_id !== undefined) params.append("life_event_id", String(life_event_id));
        const data = await api.get<unknown>(`/roadmap/milestones?${params.toString()}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ milestones: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "roadmap_milestones_create",
    {
      title: "Create milestone",
      description: "Creates one roadmap milestone.",
      inputSchema: z
        .object({
          life_event_id: z.number().int().min(1).nullable().optional().describe("Related life event ID"),
          date: dateSchema.describe("Milestone date, YYYY-MM-DD"),
          target_amount: z.number().min(0).describe("Target amount"),
          note: z.string().nullable().optional().describe("Note"),
          source: z.string().optional().default("manual").describe("Source label"),
          source_snapshot: z.record(z.unknown()).nullable().optional().describe("Optional source snapshot"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/roadmap/milestones", input);
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
    "roadmap_milestones_preview_from_simulation",
    {
      title: "Preview simulated milestones",
      description: "Previews milestones generated from the simulation without saving them.",
      inputSchema: milestoneSimulationInputSchema,
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ life_event_id, ...payload }) => {
      try {
        const data = await api.post<unknown>(`/roadmap/life-events/${life_event_id}/milestones/from-simulation/preview`, payload);
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
    "roadmap_milestones_apply_from_simulation",
    {
      title: "Apply simulated milestones",
      description: "Generates and saves milestones from the simulation for one life event.",
      inputSchema: milestoneSimulationInputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ life_event_id, ...payload }) => {
      try {
        const data = await api.post<unknown>(`/roadmap/life-events/${life_event_id}/milestones/from-simulation`, payload);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ milestones: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
