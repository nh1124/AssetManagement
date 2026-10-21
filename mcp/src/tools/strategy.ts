// ============================================================
// Budget month copy and 物品の取り置き's plan rows
// ============================================================

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { api } from "../api-client.js";
import { toStructured } from "../utils.js";

type JsonObject = Record<string, unknown>;

const periodSchema = z.string().regex(/^\d{4}-\d{2}$/);

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function withoutUndefined(input: JsonObject): JsonObject {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}

const reserveRange = {
  start_period: periodSchema,
  end_period: periodSchema,
  base: z.enum(["saved", "remaining"]).describe("saved: the earmark's saved monthly amount (取り置きに設定した月額); remaining: what reaches the target by the replacement month (残り期間に合わせる)"),
  held: z.enum(["recent", "even"]).describe("How the amount the earmark already holds comes off: recent (the nearest months first) or even (the same amount every month to the replacement)"),
};

export function registerStrategyTools(server: McpServer): void {
  server.registerTool(
    "product_reserve_plan_preview",
    {
      title: "Preview the plan of product earmarks",
      description: "物品の取り置きから計画を作成: per month and funding account, the rows earmarks with linked products would get for a range (at most 24 months), less what they already hold; no month after the replacement. Returns a fingerprint for product_reserve_plan_apply.",
      inputSchema: z.object(reserveRange).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/budget-plans/product-reserves/preview", input as JsonObject);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: toStructured(data) };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${errorText(err)}` }] };
      }
    },
  );

  server.registerTool(
    "product_reserve_plan_apply",
    {
      title: "Make the plan of product earmarks",
      description: "Writes the previewed earmark rows, replacing those earmarks' rows in the range whatever wrote them. Pass the fingerprint from product_reserve_plan_preview only after the user agreed to that preview.",
      inputSchema: z.object({ ...reserveRange, fingerprint: z.string().length(64) }).strict(),
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async (input) => {
      try {
        const data = await api.post<unknown>("/budget-plans/product-reserves/apply", input as JsonObject);
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
      description: "Copies all active monthly plan lines from one period to another, replacing the target period.",
      inputSchema: z
        .object({
          source_period: periodSchema,
          target_period: periodSchema,
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
}
