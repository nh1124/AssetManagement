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
    sort_order: z.number().int().optional().default(0).describe("Sort order"),
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

const registryEntryBaseSchema = z.object({
  name: z.string().min(1).describe("Registry source name"),
  entry_type: z.enum(["asset", "item", "service", "income", "allocation", "debt"]).optional().default("service"),
  category: z.string().nullable().optional(),
  amount: z.number().optional().default(0),
  currency: z.string().optional().default("JPY"),
  frequency: z.enum(["Monthly", "Yearly", "EveryNDays", "Irregular"]).optional().default("Monthly"),
  frequency_days: z.number().int().min(1).nullable().optional(),
  day_of_month: z.number().int().min(1).max(31).optional().default(1),
  month_of_year: z.number().int().min(1).max(12).nullable().optional(),
  transaction_type: z
    .enum(["Income", "Expense", "Transfer", "LiabilityPayment", "Borrowing", "CreditExpense", "CreditAssetPurchase"])
    .optional()
    .default("Expense"),
  line_type: z.enum(["income", "expense", "allocation", "debt_payment", "borrowing", "drawdown"]).optional().default("expense"),
  budget_account_id: z.number().int().min(1).nullable().optional(),
  source_account_id: z.number().int().min(1).nullable().optional(),
  destination_account_id: z.number().int().min(1).nullable().optional(),
  funding_capsule_id: z.number().int().min(1).nullable().optional(),
  budget_treatment: z.enum(["auto", "expense_only", "reserve_allocation", "asset_replacement"]).optional().default("expense_only"),
  generate_recurring: z.boolean().optional().default(false),
  budget_active: z.boolean().optional().default(true),
  is_active: z.boolean().optional().default(true),
  source_product_id: z.number().int().min(1).nullable().optional(),
  source_recurring_transaction_id: z.number().int().min(1).nullable().optional(),
  note: z.string().nullable().optional(),
  start_period: periodSchema.nullable().optional(),
  end_period: periodSchema.nullable().optional(),
});

const registryEntryCreateSchema = registryEntryBaseSchema.strict();
const registryEntryUpdateSchema = registryEntryBaseSchema
  .partial()
  .extend({ id: z.number().int().min(1).describe("Registry entry ID") })
  .strict();

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function withoutUndefined(input: JsonObject): JsonObject {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

export function registerStrategyTools(server: McpServer): void {
  server.registerTool(
    "strategy_dashboard",
    {
      title: "Get strategy dashboard",
      description: "Returns the full Strategy dashboard: goals, roadmap projection, funded progress, and unallocated assets.",
      inputSchema: z
        .object({
          annual_return: z.number().optional().default(5.0),
          inflation: z.number().optional().default(2.0),
          monthly_savings: z.number().min(0).optional().default(50000),
          roadmap_interval: z.enum(["auto", "monthly", "quarterly", "annual"]).optional().default("auto"),
          allocation_mode: z.enum(["weighted", "direct"]).optional().default("weighted"),
          contribution_schedule: z.array(z.record(z.unknown())).optional(),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const params = new URLSearchParams({
          annual_return: String(input.annual_return),
          inflation: String(input.inflation),
          monthly_savings: String(input.monthly_savings),
          roadmap_interval: input.roadmap_interval,
          allocation_mode: input.allocation_mode,
        });
        if (input.contribution_schedule !== undefined) {
          params.append("contribution_schedule", JSON.stringify(input.contribution_schedule));
        }
        const data = await api.get<unknown>(`/life-events/dashboard?${params.toString()}`);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

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
      description: "Deletes a non-default Strategy budget plan and soft-deletes its monthly plan lines.",
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

  server.registerTool(
    "registry_entries_list",
    {
      title: "List registry entries",
      description: "Lists registry sources used by Strategy budget suggestions and recurring assumptions.",
      inputSchema: z
        .object({
          include_inactive: z.boolean().optional().default(true),
          entry_type: z.enum(["asset", "item", "service", "income", "allocation", "debt"]).optional(),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ include_inactive = true, entry_type }) => {
      try {
        const entries = await api.get<JsonObject[]>("/registry-entries/");
        const data = entries.filter((entry) => (
          (include_inactive || entry.is_active === true) &&
          (entry_type === undefined || entry.entry_type === entry_type)
        ));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured({ registry_entries: data }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "registry_entries_get",
    {
      title: "Get registry entry",
      description: "Gets one registry source by ID.",
      inputSchema: z.object({ id: z.number().int().min(1) }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const entries = await api.get<JsonObject[]>("/registry-entries/");
        const data = entries.find((entry) => entry.id === id);
        if (!data) return { content: [{ type: "text", text: `Error: Registry entry ${id} not found` }] };
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "registry_entries_create",
    {
      title: "Create registry entry",
      description: "Creates a registry source. Use budget_active=true to make it appear as a Strategy budget source.",
      inputSchema: registryEntryCreateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/registry-entries/", withoutUndefined(input as JsonObject));
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "registry_entries_update",
    {
      title: "Update registry entry",
      description: "Updates a registry source. Omitted fields are preserved by reading the current entry first.",
      inputSchema: registryEntryUpdateSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ id, ...patch }) => {
      try {
        const entries = await api.get<JsonObject[]>("/registry-entries/");
        const current = entries.find((entry) => entry.id === id);
        if (!current) return { content: [{ type: "text", text: `Error: Registry entry ${id} not found` }] };
        const body = withoutUndefined({ ...current, ...patch });
        delete body.id;
        delete body.budget_account_name;
        delete body.source_account_name;
        delete body.destination_account_name;
        delete body.funding_capsule_name;
        delete body.recurring_transaction_id;
        delete body.created_at;
        delete body.updated_at;
        const data = await api.put<unknown>(`/registry-entries/${id}`, body);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "registry_entries_delete",
    {
      title: "Delete registry entry",
      description: "Soft-deletes a registry source and disables its budget/recurring generation.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Registry entry ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/registry-entries/${id}`);
        return { content: [{ type: "text", text: `Deleted registry entry ${id}` }], structuredContent: toStructured(data ?? { id }) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );
}
