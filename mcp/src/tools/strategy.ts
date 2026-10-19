// ============================================================
// Strategy planning CRUD tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

type JsonObject = Record<string, unknown>;

const periodSchema = z.string().regex(/^\d{4}-\d{2}$/);
const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

const budgetPlanCreateSchema = z
  .object({
    name: z.string().min(1).describe("Budget plan name"),
    description: z.string().nullable().optional().describe("Optional description"),
    sort_order: z.number().int().optional().describe("Sort order"),
  })
  .strict();

const budgetPlanUpdateSchema = z
  .object({
    id: z.number().int().min(1).describe("Budget plan ID"),
    name: z.string().min(1).optional().describe("New name"),
    description: z.string().nullable().optional().describe("New description"),
    sort_order: z.number().int().optional().describe("Sort order"),
  })
  .strict();

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function withoutUndefined(input: JsonObject): JsonObject {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

export function registerStrategyTools(server: McpServer): void {
  server.registerTool(
    "budget_plans_list",
    {
      title: "List budget plans",
      description: "Lists available Strategy budget plans.",
      inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const data = await api.get<unknown>("/budget-plans");
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ plans: data }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "budget_plans_create",
    {
      title: "Create budget plan",
      description: "Creates a Strategy budget plan.",
      inputSchema: budgetPlanCreateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/budget-plans", withoutUndefined(input as JsonObject));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "budget_plans_update",
    {
      title: "Update budget plan",
      description: "Updates a Strategy budget plan's name, description, or sort order.",
      inputSchema: budgetPlanUpdateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const data = await api.put<unknown>(`/budget-plans/${id}`, withoutUndefined(patch as JsonObject));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "budget_plans_delete",
    {
      title: "Delete budget plan",
      description: "Deletes a non-default Strategy budget plan and the monthly plan lines it holds.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Budget plan ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/budget-plans/${id}`);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data ?? {}) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "budget_plans_copy_from",
    {
      title: "Copy budget plan",
      description: "Replaces all lines in a target budget plan with active lines from a source budget plan.",
      inputSchema: z
        .object({
          target_plan_id: z.number().int().min(1),
          source_plan_id: z.number().int().min(1),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ target_plan_id, source_plan_id }) => {
      try {
        const data = await api.post<unknown>(`/budget-plans/${target_plan_id}/copy-from?source_plan_id=${source_plan_id}`, {});
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "budget_plans_copy_period",
    {
      title: "Copy budget period",
      description: "Copies all active monthly plan lines from one period to another within a budget plan, replacing the target period.",
      inputSchema: z
        .object({
          source_period: periodSchema,
          target_period: periodSchema,
          plan_id: z.number().int().min(1).optional().describe("Budget plan ID. Omit to use the default plan."),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/budget-plans/copy-period", withoutUndefined(input as JsonObject));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "budget_plans_compare",
    {
      title: "Compare budget plans",
      description: "Compares cash-flow projections for multiple budget plans.",
      inputSchema: z
        .object({
          plan_ids: z.array(z.number().int().min(1)).min(1),
          start_period: periodSchema,
          months: z.number().int().min(1).max(36).optional().default(12),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ plan_ids, start_period, months = 12 }) => {
      try {
        const params = new URLSearchParams({
          plan_ids: plan_ids.join(","),
          start_period,
          months: String(months),
        });
        const data = await api.get<unknown>(`/budget-plans/compare?${params.toString()}`);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ comparisons: data }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

}
