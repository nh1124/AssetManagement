// ============================================================
// Goal tools: scenarios, life events, 積立設定, earmark tracking, goal-to-plan
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const periodSchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])$/);
const id = z.number().int().min(1);

const lifeEventFields = {
  name: z.string().min(1).describe("Life event name"),
  direction: z.enum(["expense", "income"]).optional().describe("expense (default) or income"),
  account_id: id.nullable().optional().describe("Account or subject the event belongs to"),
  target_date: dateSchema.describe("Target date, YYYY-MM-DD"),
  target_amount: z.number().min(0).describe("Target amount"),
  priority: z.number().int().min(1).max(3).optional().describe("Priority: 1=high, 2=medium, 3=low"),
  note: z.string().nullable().optional().describe("Optional note"),
  condition_mode: z.enum(["all", "any"]).optional().describe("How preconditions combine"),
};
const lifeEventCreateSchema = z.object({ scenario_id: id.describe("Scenario that owns the event"), ...lifeEventFields }).strict();
const lifeEventUpdateSchema = z.object(lifeEventFields).partial().extend({ id: id.describe("Life event ID") }).strict();
const contributionFields = {
  account_id: id.describe("Asset account"),
  start_period: periodSchema.describe("First month the record applies, YYYY-MM"),
  monthly_amount: z.number().min(0).describe("Monthly contribution from that month"),
  annual_return: z.number().nullable().optional().describe("Yield % from that month; null keeps the previous one"),
  note: z.string().nullable().optional(),
};

type Handler<T> = (input: T) => Promise<unknown>;

function reply(label: string, data: unknown) {
  return { content: [{ type: "text" as const, text: `${label}\n${JSON.stringify(data, null, 2)}` }], structuredContent: toStructured(data) };
}

function guarded<T>(label: string, handler: Handler<T>) {
  return async (input: T) => {
    try {
      return reply(label, await handler(input));
    } catch (err) {
      return { content: [{ type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
    }
  };
}


function only(input: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

export function registerLifeEventTools(server: McpServer): void {
  server.registerTool("life_scenarios_list", {
    title: "List scenarios",
    description: "Every scenario with its assumptions, 積立設定 records and resolved events; is_goal marks the adopted one.",
    inputSchema: z.object({}).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Scenarios:", async () => api.get<unknown>("/life-scenarios")));

  server.registerTool("life_scenarios_simulate", {
    title: "Simulate scenarios",
    description: "Runs the account-by-account simulation: net worth bands, each event's chance to happen and be affordable, the branches most paths take (likely_path), per-account balances.",
    inputSchema: z.object({ ids: z.array(id).min(1).describe("Scenario IDs") }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Simulation:", async ({ ids }: { ids: number[] }) => api.get<unknown>(`/life-scenarios/compare?ids=${ids.join(",")}`)));

  server.registerTool("life_events_list", {
    title: "List life events",
    description: "The goal scenario's events (or another scenario's) with the earmarks counted toward them and the funding those give.",
    inputSchema: z.object({ scenario_id: id.optional() }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Life events:", async ({ scenario_id }: { scenario_id?: number }) =>
    api.get<unknown>(`/life-events/with-progress${scenario_id ? `?scenario_id=${scenario_id}` : ""}`)));

  server.registerTool("life_events_create", {
    title: "Create life event",
    description: "Creates a life event in a scenario: kind, account or subject, name, target amount and date, priority, note.",
    inputSchema: lifeEventCreateSchema, annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  }, guarded("Created life event:", async (input: z.infer<typeof lifeEventCreateSchema>) => api.post<unknown>("/life-events/", only(input))));

  server.registerTool("life_events_update", {
    title: "Update life event",
    description: "Updates a life event's fields.",
    inputSchema: lifeEventUpdateSchema, annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Updated life event:", async ({ id: eventId, ...patch }: z.infer<typeof lifeEventUpdateSchema>) =>
    api.put<unknown>(`/life-events/${eventId}`, only(patch))));

  server.registerTool("life_events_delete", {
    title: "Delete life event",
    description: "Deletes a life event with its links and conditions; the earmarks it counted stay.",
    inputSchema: z.object({ id: id.describe("Life event ID") }).strict(), annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  }, guarded("Deleted life event:", async ({ id: eventId }: { id: number }) => api.delete<unknown>(`/life-events/${eventId}`)));

  server.registerTool("goal_earmarks_set", {
    title: "Set goal earmarks",
    description: "実績管理の設定: replaces which earmarks count toward a goal event and the percent of each that counts.",
    inputSchema: z.object({
      event_id: id.describe("Life event ID"),
      earmarks: z.array(z.object({ capsule_id: id, share: z.number().min(0).max(100).optional() }).strict()),
    }).strict(), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Goal earmarks:", async ({ event_id, earmarks }: { event_id: number; earmarks: Array<{ capsule_id: number; share?: number }> }) =>
    api.put<unknown>(`/life-events/${event_id}/earmarks`, earmarks)));

  server.registerTool("contribution_plans_create", {
    title: "Add a contribution plan record",
    description: "積立設定: from start_period, the account receives monthly_amount and earns annual_return (null keeps the previous yield).",
    inputSchema: z.object({ scenario_id: id, ...contributionFields }).strict(), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  }, guarded("Created contribution plan record:", async ({ scenario_id, ...record }: { scenario_id: number } & Record<string, unknown>) =>
    api.post<unknown>(`/life-scenarios/${scenario_id}/contribution-plans`, only(record))));

  server.registerTool("contribution_plans_update", {
    title: "Update a contribution plan record",
    description: "Changes a 積立設定 record; fields left out keep their value.",
    inputSchema: z.object(contributionFields).partial().extend({ id: id.describe("Record ID") }).strict(), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Updated contribution plan record:", async ({ id: planId, ...patch }: { id: number } & Record<string, unknown>) =>
    api.put<unknown>(`/life-scenarios/contribution-plans/${planId}`, only(patch))));

  server.registerTool("contribution_plans_delete", {
    title: "Delete a contribution plan record",
    description: "Deletes a 積立設定 record.",
    inputSchema: z.object({ id: id.describe("Record ID") }).strict(), annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  }, guarded("Deleted contribution plan record:", async ({ id: planId }: { id: number }) =>
    api.delete<unknown>(`/life-scenarios/contribution-plans/${planId}`)));

  server.registerTool("goal_plan_check", {
    title: "Goal against the plan",
    description: "For a month: per account, the goal's 積立設定 contribution against what the plan allocates.",
    inputSchema: z.object({ period: periodSchema }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Plan check:", async ({ period }: { period: string }) => api.get<unknown>(`/goal-budget/plan-check?period=${period}`)));

  server.registerTool("goal_plan_preview", {
    title: "Preview the plan from the goal",
    description: "What making the plan from the goal would write for a range of months; returns a fingerprint for goal_plan_apply.",
    inputSchema: z.object({ start_period: periodSchema, end_period: periodSchema }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Plan preview:", async (input: { start_period: string; end_period: string }) => api.post<unknown>("/goal-budget/preview", input)));

  server.registerTool("goal_plan_apply", {
    title: "Make the plan from the goal",
    description: "Writes the previewed plan rows. Pass the fingerprint from goal_plan_preview only after the user agreed to that preview.",
    inputSchema: z.object({ start_period: periodSchema, end_period: periodSchema, fingerprint: z.string().length(64) }).strict(), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  }, guarded("Applied:", async (input: { start_period: string; end_period: string; fingerprint: string }) => api.post<unknown>("/goal-budget/apply", input)));
}
