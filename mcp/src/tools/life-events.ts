// ============================================================
// Goal tools: scenarios, life events and loans, 積立設定, 期間ごとの前提, changing the goal, the goal against the plan
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
  direction: z.enum(["expense", "income", "borrowing", "repayment"]).optional().describe("expense (default), income, borrowing or repayment"),
  target_date: dateSchema.describe("Target date (a repayment's first month), YYYY-MM-DD"),
  target_amount: z.number().min(0).describe("Amount; for a repayment, the monthly payment"),
  interest_rate: z.number().min(0).max(100).nullable().optional().describe("Borrowing only: yearly interest %"),
  borrowing_event_id: id.nullable().optional().describe("Repayment only: the borrowing event it repays (same scenario)"),
  repeat_count: z.number().int().min(1).max(1200).nullable().optional().describe("Repayment only: number of monthly payments"),
  priority: z.number().int().min(1).max(3).optional().describe("Priority: 1=high, 2=medium, 3=low"),
  note: z.string().nullable().optional().describe("Optional note"),
  condition_mode: z.enum(["all", "any"]).optional().describe("How preconditions combine"),
};
const lifeEventCreateSchema = z.object({ scenario_id: id.describe("Scenario that owns the event"), ...lifeEventFields }).strict();
const lifeEventUpdateSchema = z.object(lifeEventFields).partial().extend({ id: id.describe("Life event ID") }).strict();
const contributionFields = {
  kind: z.enum(["contribution", "transfer", "withdrawal"]).optional()
    .describe("contribution (積立 into account_id), transfer (口座振替 from account_id to to_account_id), withdrawal (ライフイベントへの取り崩し from account_id toward life_event_id). Left out on create: withdrawal with life_event_id, transfer with to_account_id, else contribution"),
  account_id: id.describe("Asset account: where a contribution goes, where a transfer or withdrawal comes from"),
  to_account_id: id.nullable().optional().describe("Transfer destination: another asset account"),
  start_period: periodSchema.describe("First month the record moves money, YYYY-MM"),
  amount: z.number().min(0).optional().describe("What moves each time (never negative; more than 0 for a transfer or a withdrawal)"),
  interval_months: z.number().int().min(1).max(120).nullable().optional()
    .describe("null: once; 1: every month; 12: every year; N: every N months. Left out on create: 1 for contribution and transfer, once for withdrawal"),
  repeat_count: z.number().int().min(1).max(1200).nullable().optional().describe("How many times a repeated record moves money"),
  end_period: periodSchema.nullable().optional().describe("Last month a repeated record may move money, YYYY-MM (with repeat_count, whichever comes first)"),
  on_shortage: z.enum(["skip", "partial"]).nullable().optional()
    .describe("Transfer or withdrawal when the account holds less: skip (取引を発生させない, default for transfer) or partial (ある分だけで取引する, default for withdrawal). Nothing is moved in from elsewhere"),
  annual_return: z.number().nullable().optional().describe("Contribution only: the account's yield % from start_period until a later record names another; null keeps the previous one"),
  note: z.string().nullable().optional(),
  life_event_id: id.nullable().optional().describe("Withdrawal: an expense event of the same scenario. From the event's month on, withdrawals pay it in instalments (e.g. 老後生活, 100000 a month for 360 months)"),
};

const periodFields = {
  start_period: periodSchema.describe("First month the record applies, YYYY-MM"),
  end_period: periodSchema.nullable().optional().describe("Last month it applies (inclusive), YYYY-MM; null: to the end of the simulation"),
  annual_return: z.number().nullable().optional()
    .describe("The scenario's default yield % in these months (for accounts whose 積立設定 names none); null keeps what applies otherwise"),
  inflation: z.number().nullable().optional().describe("Inflation % in these months; null keeps what applies otherwise"),
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
    description: "The goal scenario's events (or another scenario's) with the earmark made for each and the funding it gives.",
    inputSchema: z.object({ scenario_id: id.optional() }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Life events:", async ({ scenario_id }: { scenario_id?: number }) =>
    api.get<unknown>(`/life-events/with-progress${scenario_id ? `?scenario_id=${scenario_id}` : ""}`)));

  server.registerTool("life_events_create", {
    title: "Create life event",
    description: "Creates a life event in a scenario: kind (expense, income, borrowing, repayment), name, amount and date, priority, note; a repayment names its borrowing and number of months. Which accounts pay it: contribution_plans_create with life_event_id (a one-off withdrawal record).",
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
    description: "Deletes a life event with its links and conditions; its earmark stays but no longer belongs to the goal.",
    inputSchema: z.object({ id: id.describe("Life event ID") }).strict(), annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  }, guarded("Deleted life event:", async ({ id: eventId }: { id: number }) => api.delete<unknown>(`/life-events/${eventId}`)));

  server.registerTool("life_scenarios_goal_preview", {
    title: "Preview changing the goal",
    description: "What making a scenario the goal would do to the current goal's earmarks: which carry to the same event, and which earmarks the new goal would get.",
    inputSchema: z.object({ id: id.describe("Scenario ID") }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Goal change preview:", async ({ id: scenarioId }: { id: number }) => api.get<unknown>(`/life-scenarios/${scenarioId}/goal-preview`)));

  server.registerTool("life_scenarios_make_goal", {
    title: "Make a scenario the goal",
    description: "Makes the scenario the goal. earmarks: keep (default) leaves the old goal's earmarks; carry moves them to the same events; replace deletes them (their money returns to the accounts), retires the old goal's plan rows from this month and makes new earmarks. Ask the user before replace.",
    inputSchema: z.object({ id: id.describe("Scenario ID"), earmarks: z.enum(["keep", "replace", "carry"]).optional() }).strict(),
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  }, guarded("Goal:", async ({ id: scenarioId, earmarks }: { id: number; earmarks?: string }) =>
    api.post<unknown>(`/life-scenarios/${scenarioId}/goal`, { earmarks: earmarks ?? "keep" })));

  server.registerTool("contribution_plans_create", {
    title: "Add a contribution plan record",
    description: "積立設定 record (records add up): 積立 into an account, 口座振替 between accounts, or ライフイベントへの取り崩し toward an expense event, once or on a schedule (every N months, N times or until a month). E.g. 証券口座 750000 once in 2028-10 for 結婚; 貯蓄口座 100000 every month from 2051-01, 360 times, for 老後生活. The plan follows through 計画への反映 (plan_reflection_*): it earmarks a withdrawal's account until its first month, draws it down in each month, and writes transfers with their source.",
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

  server.registerTool("assumption_periods_create", {
    title: "Add an assumption period",
    description: "期間ごとの前提: from start_period to end_period the scenario's default yield and/or inflation are these values instead of the scenario's own. At least one of annual_return and inflation. Where records overlap the latest start wins; an account's own 積立設定 yield still comes first. The simulation reads a calendar year's values at its first month. 変動率 and 税率 stay common to all scenarios (simulation config).",
    inputSchema: z.object({ scenario_id: id, ...periodFields }).strict(), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
  }, guarded("Created assumption period:", async ({ scenario_id, ...record }: { scenario_id: number } & Record<string, unknown>) =>
    api.post<unknown>(`/life-scenarios/${scenario_id}/assumption-periods`, only(record))));

  server.registerTool("assumption_periods_update", {
    title: "Update an assumption period",
    description: "Changes a 期間ごとの前提 record; fields left out keep their value.",
    inputSchema: z.object(periodFields).partial().extend({ id: id.describe("Record ID") }).strict(), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Updated assumption period:", async ({ id: periodId, ...patch }: { id: number } & Record<string, unknown>) =>
    api.put<unknown>(`/life-scenarios/assumption-periods/${periodId}`, only(patch))));

  server.registerTool("assumption_periods_delete", {
    title: "Delete an assumption period",
    description: "Deletes a 期間ごとの前提 record.",
    inputSchema: z.object({ id: id.describe("Record ID") }).strict(), annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  }, guarded("Deleted assumption period:", async ({ id: periodId }: { id: number }) =>
    api.delete<unknown>(`/life-scenarios/assumption-periods/${periodId}`)));

  server.registerTool("goal_plan_check", {
    title: "Goal against the plan",
    description: "For a month: per account, the goal's 積立設定 contribution against what the plan allocates.",
    inputSchema: z.object({ period: periodSchema }).strict(), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  }, guarded("Plan check:", async ({ period }: { period: string }) => api.get<unknown>(`/goal-budget/plan-check?period=${period}`)));
}
