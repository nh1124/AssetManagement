// ============================================================
// Monthly planning and review tools
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { fetchAccounts } from "../domain-guidance.js";
import { toStructured } from "../utils.js";

const periodSchema = z.string().regex(/^\d{4}-\d{2}$/);

const planLineTypeSchema = z.enum(["income", "expense", "allocation", "debt_payment", "borrowing", "drawdown"]);
const planTargetTypeSchema = z.enum(["account", "capsule", "life_event", "product", "manual"]);
const cashTreatmentSchema = z.enum(["auto", "cash", "non_cash"]);

const monthlyPlanLinePayloadKeys = [
  "plan_id",
  "target_period",
  "line_type",
  "target_type",
  "target_id",
  "account_id",
  "source_account_id",
  "name",
  "amount",
  "source",
  "source_kind",
  "source_id",
  "identity_key",
  "manual_override",
  "cash_treatment",
  "recurring_transaction_id",
  "is_active",
] as const;

const monthlyPlanLineApiSchema = z
  .object({
    plan_id: z.number().int().min(1).optional().describe("Budget plan ID. Omit to use the default plan."),
    target_period: periodSchema.describe("Target period, YYYY-MM"),
    line_type: planLineTypeSchema.describe("Monthly plan line type"),
    target_type: planTargetTypeSchema.optional().describe("Target entity kind"),
    target_id: z.number().int().min(1).optional().describe("Target entity ID"),
    account_id: z.number().int().min(1).optional().describe("Account ID"),
    source_account_id: z.number().int().min(1).optional().describe("Source account ID"),
    name: z.string().optional().describe("Display name"),
    amount: z.number().optional().describe("Plan amount"),
    source: z.string().optional().describe("Source marker"),
    source_kind: z.string().optional().describe("Source identity kind"),
    source_id: z.number().int().min(1).optional().describe("Source identity ID"),
    identity_key: z.string().optional().describe("Stable source identity key"),
    manual_override: z.boolean().optional().describe("Whether this line manually overrides generated suggestions"),
    cash_treatment: cashTreatmentSchema.optional().describe("Cash-flow treatment"),
    recurring_transaction_id: z.number().int().min(1).optional().describe("Linked recurring transaction ID"),
    is_active: z.boolean().optional().describe("Whether the line is active"),
  })
  .strict();

const monthlyPlanLineCreateSchema = monthlyPlanLineApiSchema.describe("Monthly plan line create payload. Omit id.");
const monthlyPlanLineUpdateSchema = monthlyPlanLineApiSchema
  .extend({
    id: z.number().int().min(1).describe("Existing monthly plan line ID. Required for updates."),
  })
  .strict()
  .describe("Monthly plan line update payload. Requires id.");
const monthlyPlanLineSaveSchema = z.union([monthlyPlanLineUpdateSchema, monthlyPlanLineCreateSchema]);

function pickMonthlyPlanLinePayload(input: object, includeId: boolean): Record<string, unknown> {
  const source = input as Record<string, unknown>;
  const payload: Record<string, unknown> = {};
  if (includeId && source.id !== undefined) payload.id = source.id;
  for (const key of monthlyPlanLinePayloadKeys) {
    if (source[key] !== undefined) payload[key] = source[key];
  }
  return payload;
}

export function toMonthlyPlanLineCreatePayload(input: object): Record<string, unknown> {
  return pickMonthlyPlanLinePayload(input, false);
}

export function toMonthlyPlanLineUpdatePayload(input: object): Record<string, unknown> {
  return pickMonthlyPlanLinePayload(input, true);
}

export function registerMonthlyPlanningTools(server: McpServer): void {
  server.registerTool(
    "monthly_plan_summary",
    {
      title: "Get monthly plan summary",
      description: "Returns monthly cash-flow plan summary and projected cash flow.",
      inputSchema: z
        .object({
          period: periodSchema.optional().describe("Target period, YYYY-MM"),
          plan_id: z.number().int().min(1).optional().describe("Budget plan ID. Omit to use the default plan."),
          cash_flow_start_period: periodSchema.optional().describe("Projection start period, YYYY-MM"),
          cash_flow_months: z.number().int().min(1).max(36).optional().default(12),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ period, plan_id, cash_flow_start_period, cash_flow_months = 12 }) => {
      try {
        const params = new URLSearchParams();
        if (period !== undefined) params.append("period", period);
        if (plan_id !== undefined) params.append("plan_id", String(plan_id));
        if (cash_flow_start_period !== undefined) params.append("cash_flow_start_period", cash_flow_start_period);
        params.append("cash_flow_months", String(cash_flow_months));
        const data = await api.get<unknown>(`/life-events/budget-summary?${params.toString()}`);
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
    "monthly_plan_lines_list",
    {
      title: "List monthly plan lines",
      description: "Returns monthly plan lines for a period.",
      inputSchema: z
        .object({
          period: periodSchema.optional().describe("Target period, YYYY-MM"),
          plan_id: z.number().int().min(1).optional().describe("Budget plan ID. Omit to use the default plan."),
        })
        .strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ period, plan_id }) => {
      try {
        const params = new URLSearchParams();
        if (period !== undefined) params.append("period", period);
        if (plan_id !== undefined) params.append("plan_id", String(plan_id));
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await api.get<unknown>(`/life-events/monthly-plan-lines${query}`);
        return {
          content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
          structuredContent: toStructured({ plan_lines: data }),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "monthly_plan_lines_save_batch",
    {
      title: "Save monthly plan lines",
      description: "Creates monthly plan lines without id and updates lines with id. Updates require an existing id.",
      inputSchema: z.object({ lines: z.array(monthlyPlanLineSaveSchema).min(1) }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ lines }) => {
      try {
        const creates = lines
          .filter((line) => !("id" in line) || line.id === undefined)
          .map((line) => toMonthlyPlanLineCreatePayload(line));
        const updates = lines
          .filter((line) => "id" in line && line.id !== undefined)
          .map((line) => toMonthlyPlanLineUpdatePayload(line));
        const created = creates.length > 0
          ? await api.post<unknown>("/life-events/monthly-plan-lines", creates)
          : null;
        const updated = updates.length > 0
          ? await api.put<unknown>("/life-events/monthly-plan-lines/batch", updates)
          : null;
        const data = { created, updated };
        return {
          content: [{ type: "text", text: `Saved monthly plan lines:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "monthly_plan_lines_preview",
    {
      title: "Preview monthly plan lines",
      description: "Validates monthly plan lines without saving them. Use before monthly_plan_lines_save_batch.",
      inputSchema: z.object({ lines: z.array(monthlyPlanLineSaveSchema).min(1) }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ lines }) => {
      try {
        const accounts = await fetchAccounts();
        const accountById = new Map(accounts.map((account) => [account.id, account]));
        const previews = lines.map((line, index) => {
          const errors: string[] = [];
          const warnings: string[] = [];
          const account = line.account_id ? accountById.get(line.account_id) : undefined;
          const sourceAccount = line.source_account_id ? accountById.get(line.source_account_id) : undefined;
          if (line.account_id && !account) errors.push(`account_id ${line.account_id} was not found.`);
          if (line.source_account_id && !sourceAccount) errors.push(`source_account_id ${line.source_account_id} was not found.`);
          if (line.line_type === "expense" && account && account.account_type !== "expense") {
            warnings.push(`Expense plan line points to ${account.account_type} account "${account.name}".`);
          }
          if (line.line_type === "allocation" && account && account.account_type !== "asset") {
            warnings.push(`Allocation plan line usually points to an asset account or capsule, not ${account.account_type}.`);
          }
          const amount = line.amount ?? 0;
          const isUpdate = "id" in line && line.id !== undefined;
          const submitPayload = isUpdate
            ? toMonthlyPlanLineUpdatePayload(line)
            : toMonthlyPlanLineCreatePayload(line);
          if (amount < 0) warnings.push("Negative amount is unusual for monthly plan lines.");
          return {
            index,
            operation: isUpdate ? "update" : "create",
            ok_to_submit: errors.length === 0,
            line,
            submit_payload: submitPayload,
            account: account ? { id: account.id, name: account.name, account_type: account.account_type } : null,
            source_account: sourceAccount ? { id: sourceAccount.id, name: sourceAccount.name, account_type: sourceAccount.account_type } : null,
            validation: { ok: errors.length === 0, errors, warnings },
          };
        });
        const data = {
          ok_to_submit: previews.every((preview) => preview.ok_to_submit),
          line_count: lines.length,
          total_amount: lines.reduce((sum, line) => sum + (line.amount ?? 0), 0),
          previews,
        };
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
    "monthly_plan_lines_delete",
    {
      title: "Delete monthly plan line",
      description: "Soft-deletes one monthly plan line.",
      inputSchema: z.object({ id: z.number().int().min(1).describe("Plan line ID") }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        const data = await api.delete<unknown>(`/life-events/monthly-plan-lines/${id}`);
        return {
          content: [{ type: "text", text: `Deleted monthly plan line ${id}:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );

  server.registerTool(
    "monthly_reviews_get",
    {
      title: "Get monthly review",
      description: "Returns the monthly review for a period or an empty draft.",
      inputSchema: z.object({ period: periodSchema.optional().describe("Target period, YYYY-MM") }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ period }) => {
      try {
        const query = period ? `?period=${encodeURIComponent(period)}` : "";
        const data = await api.get<unknown>(`/monthly-reviews/${query}`);
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
    "monthly_reviews_upsert",
    {
      title: "Upsert monthly review",
      description: "Creates or updates reflection and next actions for one month.",
      inputSchema: z
        .object({
          target_period: periodSchema.describe("Target period, YYYY-MM"),
          reflection: z.string().optional().default("").describe("Reflection text"),
          next_actions: z.string().optional().default("").describe("Next action text"),
        })
        .strict(),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.put<unknown>("/monthly-reviews/", input);
        return {
          content: [{ type: "text", text: `Saved monthly review:\n${JSON.stringify(data, null, 2)}` }],
          structuredContent: toStructured(data),
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err instanceof Error ? err.message : String(err)}` }] };
      }
    },
  );
}
