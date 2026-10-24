// ============================================================
// The rest of what the screens do (WP27: everything but account operations -- sign-in, registration,
// password, MFA -- and the AI's own permission settings)
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z, type ZodRawShape } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

const id = z.number().int().min(1);
const periodSchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])$/);
const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

type Args = Record<string, unknown>;

function only(input: Args): Args {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

function query(input: Args): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(input)) if (value !== undefined && value !== null) params.append(key, String(value));
  const text = params.toString();
  return text ? `?${text}` : "";
}

function register(server: McpServer, name: string, title: string, description: string, shape: ZodRawShape,
  kind: "read" | "write" | "delete", handler: (input: Args) => Promise<unknown>): void {
  server.registerTool(name, {
    title, description, inputSchema: z.object(shape).strict(),
    annotations: { readOnlyHint: kind === "read", destructiveHint: kind === "delete", idempotentHint: kind !== "write", openWorldHint: false },
  }, async (input: Args) => {
    try {
      const data = await handler(input);
      return { content: [{ type: "text" as const, text: `${title}:\n${JSON.stringify(data ?? {}, null, 2)}` }], structuredContent: toStructured(data ?? {}) };
    } catch (err) {
      return { content: [{ type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
    }
  });
}

const conditionFields = {
  metric: z.enum(["net_worth", "free_cash", "account_balance", "capsule_claim", "goal_progress", "member_age", "date_reached"])
    .describe("net_worth, free_cash (使える現金), account_balance, capsule_claim (an earmark's held amount), goal_progress, member_age, date_reached"),
  comparator: z.enum(["gte", "lte", "eq"]).optional(),
  threshold_minor: z.number().int().nullable().optional().describe("Money threshold in minor units"),
  threshold_number: z.number().nullable().optional(),
  threshold_date: dateSchema.nullable().optional(),
  reference_id: id.nullable().optional().describe("The account, earmark or household member the metric reads"),
  note: z.string().nullable().optional(),
};

export function registerUiOperationTools(server: McpServer): void {
  // Scenarios
  register(server, "life_scenarios_create", "Create a scenario", "Creates a scenario (its 前提 copied from the goal).", { name: z.string().min(1) }, "write",
    ({ name }) => api.post<unknown>("/life-scenarios", { name }));
  register(server, "life_scenarios_duplicate", "Duplicate a scenario", "Copies a scenario with its events, links, preconditions, 積立設定 and 期間ごとの前提.",
    { id, name: z.string().min(1) }, "write", ({ id: scenarioId, name }) => api.post<unknown>(`/life-scenarios/${scenarioId}/duplicate`, { name }));
  register(server, "life_scenarios_update", "Update a scenario", "Renames a scenario or changes its 前提 (horizon, default yield, inflation).",
    { id, name: z.string().min(1).optional(), annual_return: z.number().optional(), inflation: z.number().optional(), horizon_years: z.number().int().min(1).max(60).optional() },
    "write", ({ id: scenarioId, ...patch }) => api.put<unknown>(`/life-scenarios/${scenarioId}`, only(patch)));
  register(server, "life_scenarios_delete", "Delete a scenario", "Deletes a scenario that is not the goal, with its events.", { id }, "delete",
    ({ id: scenarioId }) => api.delete<unknown>(`/life-scenarios/${scenarioId}`));

  // Links between life events (構成)
  register(server, "life_event_links_list", "List life event links", "The links of a scenario's events.", { scenario_id: id.optional() }, "read",
    (input) => api.get<unknown>(`/life-events/links${query(input)}`));
  register(server, "life_event_links_create", "Link two life events", "The second event follows the first (after offset_months; 0 is the child's own date).",
    { from_event_id: id, to_event_id: id, kind: z.literal("after").default("after"), offset_months: z.number().int().min(0).optional(), note: z.string().nullable().optional() },
    "write", (input) => api.post<unknown>("/life-events/links", only(input)));
  register(server, "life_event_links_delete", "Delete a life event link", "Removes a link.", { id }, "delete", ({ id: linkId }) => api.delete<unknown>(`/life-events/links/${linkId}`));

  // Preconditions (前提条件)
  register(server, "life_event_conditions_list", "List preconditions", "An event's preconditions, judged as of a date.", { event_id: id, as_of: dateSchema.optional() }, "read",
    ({ event_id, as_of }) => api.get<unknown>(`/life-events/${event_id}/conditions${query({ as_of })}`));
  register(server, "life_event_conditions_create", "Add a precondition", "Adds a precondition the event needs to happen.", { event_id: id, ...conditionFields }, "write",
    ({ event_id, ...body }) => api.post<unknown>(`/life-events/${event_id}/conditions`, only(body)));
  register(server, "life_event_conditions_update", "Update a precondition", "Changes a precondition.", { event_id: id, condition_id: id, ...conditionFields }, "write",
    ({ event_id, condition_id, ...body }) => api.put<unknown>(`/life-events/${event_id}/conditions/${condition_id}`, only(body)));
  register(server, "life_event_conditions_delete", "Delete a precondition", "Removes a precondition.", { event_id: id, condition_id: id }, "delete",
    ({ event_id, condition_id }) => api.delete<unknown>(`/life-events/${event_id}/conditions/${condition_id}`));

  // Household (世帯)
  register(server, "household_members_list", "List household members", "The household members (ages for preconditions).", {}, "read", () => api.get<unknown>("/household-members"));
  register(server, "household_members_create", "Add a household member", "Adds a member.", { name: z.string().min(1), relation: z.string().nullable().optional(), birth_date: dateSchema }, "write",
    (input) => api.post<unknown>("/household-members", only(input)));
  register(server, "household_members_update", "Update a household member", "Changes a member.",
    { id, name: z.string().min(1).optional(), relation: z.string().nullable().optional(), birth_date: dateSchema.optional() }, "write",
    ({ id: memberId, ...patch }) => api.put<unknown>(`/household-members/${memberId}`, only(patch)));
  register(server, "household_members_delete", "Delete a household member", "Removes a member.", { id }, "delete", ({ id: memberId }) => api.delete<unknown>(`/household-members/${memberId}`));

  // The plan page's account editor (records)
  register(server, "plan_account_month", "An account's month in the plan", "An account's sections with every record behind each budget (goal, automatic transaction, card estimate, user) and the month's automatic transactions.",
    { period: periodSchema, account_id: id }, "read", ({ period, account_id }) => api.get<unknown>(`/plan/${period}/accounts/${account_id}`));
  register(server, "plan_records_add", "Add a plan record", "Adds the user's record to a section (several per section, one per name). With automatic, it becomes an automatic transaction from start_period (records_transactions also posts it on its day; otherwise it only budgets).",
    {
      period: periodSchema, account_id: id, section: z.enum(["income", "expense", "allocation", "debt_payment", "borrowing", "drawdown"]),
      amount: z.number().min(0), name: z.string().max(200).optional(),
      automatic: z.object({
        frequency: z.enum(["Monthly", "Yearly"]).default("Monthly"), day_of_month: z.number().int().min(1).max(31).default(1),
        start_period: periodSchema, end_period: periodSchema.nullable().optional(), counter_account_id: id,
        records_transactions: z.boolean().default(false),
      }).strict().optional(),
    }, "write", (input) => api.post<unknown>("/plan/records", only(input)));
  register(server, "plan_records_update", "Update a plan record", "Changes the amount or name of the user's record.", { id, amount: z.number().min(0), name: z.string().max(200).optional() }, "write",
    ({ id: recordId, ...body }) => api.put<unknown>(`/plan/records/${recordId}`, only(body)));
  register(server, "plan_records_delete", "Delete a plan record", "Deletes the user's record.", { id }, "delete", ({ id: recordId }) => api.delete<unknown>(`/plan/records/${recordId}`));

  // Earmark money (取り置きの拠出・使用・確保額)
  register(server, "capsule_drawdowns_list", "List an earmark's uses", "What was used from an earmark.", { capsule_id: id }, "read",
    ({ capsule_id }) => api.get<unknown>(`/capsules/${capsule_id}/drawdowns`));
  register(server, "capsules_contribute", "Set money aside in an earmark", "Moves money into an earmark from an account.",
    { capsule_id: id, amount: z.number().positive(), from_account_id: id, contribution_date: dateSchema.optional() }, "write",
    ({ capsule_id, ...body }) => api.post<unknown>(`/capsules/${capsule_id}/contribute`, only(body)));
  register(server, "capsules_drawdown", "Use money from an earmark", "Records a payment or a diversion out of an earmark.",
    { capsule_id: id, amount: z.number().positive(), from_account_id: id, to_account_id: id, kind: z.enum(["as_intended", "diverted"]).describe("as_intended: paid for what it was set aside for; diverted: used for something else"), date: dateSchema, description: z.string(), note: z.string().nullable().optional() },
    "write", ({ capsule_id, ...body }) => api.post<unknown>(`/capsules/${capsule_id}/drawdown`, only(body)));
  register(server, "capsules_set_account_claim", "Adjust what an earmark holds", "Sets what an earmark holds at one account.",
    { capsule_id: id, account_id: id, target_amount: z.number().min(0) }, "write",
    ({ capsule_id, ...body }) => api.post<unknown>(`/capsules/${capsule_id}/account-claim`, body));

  // Depreciation from the ledger
  register(server, "depreciation_preview", "Preview a depreciation", "The periods and amounts a fixed asset can depreciate next.", { product_id: id }, "read",
    (input) => api.get<unknown>(`/depreciations/preview${query(input)}`));
  register(server, "depreciation_record", "Record a depreciation", "Posts a fixed asset's depreciation for a period.",
    { product_id: id, period: periodSchema, amount: z.number().positive().optional(), date: dateSchema.optional(), expense_account_id: id.optional(), asset_account_id: id.optional() },
    "write", (input) => api.post<unknown>("/depreciations", only(input)));
  register(server, "depreciation_amend", "Amend a depreciation", "Changes a recorded depreciation.",
    { id, amount: z.number().positive(), date: dateSchema.optional(), expense_account_id: id.optional() }, "write",
    ({ id: depreciationId, ...body }) => api.put<unknown>(`/depreciations/${depreciationId}`, only(body)));

  // Automatic recordings waiting for the user (家計簿 › 自動取引の未反映)
  register(server, "transaction_proposals_list", "List pending recordings", "Recordings waiting to be posted or rejected.", { status: z.string().optional(), origin: z.string().optional() }, "read",
    (input) => api.get<unknown>(`/transactions/proposals${query(input)}`));
  register(server, "transaction_proposals_approve", "Post a pending recording", "Posts a pending recording as a transaction.", { id }, "write",
    ({ id: proposalId }) => api.post<unknown>(`/transactions/proposals/${proposalId}/approve`, {}));
  register(server, "transaction_proposals_reject", "Reject a pending recording", "Rejects a pending recording.", { id, note: z.string().nullable().optional() }, "write",
    ({ id: proposalId, note }) => api.post<unknown>(`/transactions/proposals/${proposalId}/reject`, only({ note })));

  // Notifications, data health, reconciliation
  register(server, "notifications_list", "List notifications", "The notifications shown in the inbox.", {}, "read", () => api.get<unknown>("/notifications"));
  register(server, "notifications_decide", "Snooze or dismiss a notification", "snooze until a time (後で確認), dismiss (見送り) or reopen.",
    { id, action: z.enum(["snooze", "dismiss", "reopen"]), until: z.string().optional().describe("ISO date-time, for snooze") }, "write",
    ({ id: notificationId, ...body }) => api.post<unknown>(`/notifications/${notificationId}/decision`, only(body)));
  register(server, "data_health_check", "Check data health", "The data issues the user can fix and where: closed entries in the ledger, earmark funding in Earmarks, and negative amounts set aside or accounts holding less than their earmarks in Assets > Accounts.", {}, "read", () => api.get<unknown>("/data/health"));
  register(server, "reconcile_account", "Reconcile an account", "Compares an account's ledger balance with a statement balance as of a date.",
    { account_id: id, as_of: dateSchema, statement: z.number(), currency: z.string().optional() }, "read",
    ({ account_id, ...input }) => api.get<unknown>(`/analysis/reconcile/${account_id}${query(input)}`));
  register(server, "reconcile_adjust", "Post a reconciliation adjustment", "Posts the difference against a counter account so the ledger matches the statement.",
    { account_id: id, as_of: dateSchema, statement: z.number(), counter_account_id: id, capsule_id: id.nullable().optional(), note: z.string().nullable().optional(),
      currency: z.string().optional(), expected_ledger_minor: z.number().int().optional() }, "write",
    ({ account_id, ...body }) => api.post<unknown>(`/analysis/reconcile/${account_id}/adjust`, only(body)));

  // Reads the screens show
  register(server, "analysis_account_flows", "Account flows", "Each account's movements over a range.",
    { start_date: dateSchema, end_date: dateSchema, grain: z.string().optional(), account_types: z.string().optional(), include_zero: z.boolean().optional() }, "read",
    (input) => api.get<unknown>(`/analysis/account-flows${query(input)}`));
  register(server, "analysis_account_transactions", "An account's transactions", "The transactions of one account over a range.",
    { account_id: id, start_date: dateSchema, end_date: dateSchema, limit: z.number().int().min(1).max(500).optional(), offset: z.number().int().min(0).optional() }, "read",
    (input) => api.get<unknown>(`/analysis/account-transactions${query(input)}`));
  register(server, "analysis_net_worth_history", "Net worth history", "Month-end net worth for the last months.", { months: z.number().int().min(1).max(240).optional() }, "read",
    (input) => api.get<unknown>(`/analysis/net-worth-history${query(input)}`));
  register(server, "automatic_scheduled", "The month's automatic transactions", "The automatic transactions and depreciation due in a month, posted or to come, and whether each only budgets.",
    { period: periodSchema }, "read", (input) => api.get<unknown>(`/automatic-recordings/scheduled${query(input)}`));
  register(server, "transactions_get", "Get a transaction", "One transaction with its journal entries.", { id }, "read", ({ id: transactionId }) => api.get<unknown>(`/transactions/${transactionId}`));
}
